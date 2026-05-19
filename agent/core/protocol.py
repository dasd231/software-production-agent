"""Action 协议：Pydantic 校验 + 与执行器字典互转（高质量守门）。

函数流程图：
    parse_and_validate_action_line(line)
      -> 直接 json.loads()
      -> 失败时 _extract_json_object()
          -> 去掉 ```json fence
          -> 从噪声文本中扫描第一个平衡 JSON 对象
          -> 正确跳过字符串里的 { / }
      -> ActionDTO.model_validate()
          -> action 白名单
          -> args 形状和 timeout 数值校验
      -> to_executor_dict()

    validate_action_dict(obj)
      -> ActionDTO.model_validate()
      -> to_executor_dict()

你可以继续练算法/工程化的点：
    1. JSON 抽取：当前是平衡括号扫描；可以升级成 streaming decoder 多候选容错。
    2. 协议 schema：当前集中在 Pydantic validator；可以拆 per-action DTO/registry。
    3. 数值校验：当前仅校验 timeout；后续可扩展成本、风险、权限预算。
    4. 兼容性：schema_version 未来可加到 action，支持多版本 action 协议迁移。
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
"""
action协议
Pydantic 校验 + 与执行器字典互转"
负责在 LLM 输出和执行器之间建立强类型、高保真的契约

"""
#白名单
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "write_file",
        "read_file",
        "run_command",
        "list_files",
        "finish",
        "git_status",
        "git_init",
        "workspace_index",
        "mcp_call",
        "mcp_capabilities",
        "production_check",
        "web_search",
        "chain_registry",
        "resource_registry",
        "integration_catalog",
        "integration_embed_plan",
        "model_runtime_status",
        "model_admission_status",
        "model_admission_acquire",
        "model_admission_release",
        "model_admission_renew",
        "model_route_plan",
        "enterprise_stack_plan",
        "distributed_platform_plan",
        "distributed_workload_catalog",
        "distributed_job_plan",
        "project_model_program_plan",
        "project_holdout_benchmark_build",
        "project_holdout_evaluate",
        "github_corpus_program_plan",
        "github_corpus_status",
        "github_corpus_scheduler_plan",
        "github_corpus_scheduler_cycle",
        "github_corpus_flywheel_cycle",
        "github_corpus_projectization_plan",
        "github_corpus_projectize",
        "github_corpus_training_bundle",
        "github_query_plan_build",
        "github_candidate_rank",
        "corpus_feedback_plan",
        "project_repo_memory_build",
        "project_task_synthesis_build",
        "training_platform_blueprint",
        "training_recipe_plan",
        "ablation_plan_build",
        "teacher_registry",
        "teacher_task_suite_plan",
        "distillation_plan_build",
        "distillation_dataset_manifest_build",
        "teacher_prompt_batch_build",
        "teacher_execution_plan_build",
        "teacher_execution_run",
        "teacher_output_review_build",
        "distillation_export_build",
        "first_training_round_plan",
        "training_server_preflight",
        "industrial_maturity_plan",
        "enterprise_readiness_check",
        "workflow_validate",
        "innovation_radar",
        "intent_compile",
        "workflow_dry_run",
        "evidence_ledger",
        "research_feedback_report",
        "solution_publish",
        "research_synthesize",
        "training_prepare",
        "backup_model_train",
        "github_crawl_profile",
    }
)

#ActionDTO — 核心数据模型
class ActionDTO(BaseModel):
    """与 AIread.md Action 协议对齐；extra=forbid 防止静默字段污染。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["action"] = "action"
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    #动作级参数校验
    @model_validator(mode="after")
    def _args_shape(self) -> ActionDTO:
        a = self.action
        if a not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action: {a}")
        ar = self.args
        if a == "write_file":
            if "path" not in ar or "content" not in ar:
                raise ValueError("write_file requires path and content")
            if not isinstance(ar["path"], str) or not isinstance(ar["content"], str):
                raise ValueError("write_file path/content must be strings")
        elif a == "read_file":
            if "path" not in ar or not isinstance(ar["path"], str):
                raise ValueError("read_file requires string path")
        elif a == "run_command":
            if "command" not in ar or not isinstance(ar["command"], str):
                raise ValueError("run_command requires string command")
            if "timeout" in ar:
                _validate_timeout(ar["timeout"], label="timeout")
        elif a == "list_files":
            if "pattern" in ar and not isinstance(ar["pattern"], str):
                raise ValueError("pattern must be string")
        elif a == "finish":
            if "reason" in ar and not isinstance(ar["reason"], str):
                raise ValueError("reason must be string")
        elif a in ("git_status", "git_init", "workspace_index", "mcp_capabilities"):
            if ar:
                for k in ar:
                    raise ValueError(f"{a} accepts no args keys; got {k!r}")
        elif a == "production_check":
            if "include_pytest" in ar and not isinstance(ar.get("include_pytest"), bool):
                raise ValueError("production_check include_pytest must be boolean")
            if "timeout" in ar:
                _validate_timeout(ar["timeout"], label="production_check timeout")
        elif a == "mcp_call":
            if "tool" not in ar or not isinstance(ar.get("tool"), str):
                raise ValueError("mcp_call requires string tool")
            if "args" in ar and not isinstance(ar.get("args"), dict):
                raise ValueError("mcp_call args must be object when provided")
        elif a == "web_search":
            if "query" not in ar or not isinstance(ar.get("query"), str):
                raise ValueError("web_search requires string query")
            if "top_k" in ar:
                top_k = ar.get("top_k")
                if not isinstance(top_k, int) or top_k < 1:
                    raise ValueError("web_search top_k must be positive integer")
            if "provider" in ar and not isinstance(ar.get("provider"), str):
                raise ValueError("web_search provider must be string")
        elif a == "chain_registry":
            if "name" in ar and not isinstance(ar.get("name"), str):
                raise ValueError("chain_registry name must be string")
        elif a == "resource_registry":
            if "type" in ar and not isinstance(ar.get("type"), str):
                raise ValueError("resource_registry type must be string")
            if "roots" in ar:
                value = ar.get("roots")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("resource_registry roots must be string array")
        elif a == "integration_catalog":
            if "category" in ar and not isinstance(ar.get("category"), str):
                raise ValueError("integration_catalog category must be string")
        elif a == "integration_embed_plan":
            if "integration_id" not in ar or not isinstance(ar.get("integration_id"), str):
                raise ValueError("integration_embed_plan requires string integration_id")
            for key in ("resource_url", "mode", "workspace_context"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"integration_embed_plan {key} must be string")
            if "requested_capabilities" in ar:
                value = ar.get("requested_capabilities")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("integration_embed_plan requested_capabilities must be string array")
        elif a == "model_runtime_status":
            for key in ("provider", "model"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"model_runtime_status {key} must be string")
            if "probe" in ar and not isinstance(ar.get("probe"), bool):
                raise ValueError("model_runtime_status probe must be boolean")
            if "timeout" in ar:
                _validate_timeout(ar["timeout"], label="model_runtime_status timeout")
        elif a == "model_route_plan":
            if "goal" not in ar or not isinstance(ar.get("goal"), str):
                raise ValueError("model_route_plan requires string goal")
            for key in ("prompt", "business_type"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"model_route_plan {key} must be string")
            if "require_json" in ar and not isinstance(ar.get("require_json"), bool):
                raise ValueError("model_route_plan require_json must be boolean")
            if "max_output_tokens" in ar:
                value = ar.get("max_output_tokens")
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("model_route_plan max_output_tokens must be positive integer")
        elif a == "model_admission_status":
            if ar:
                for k in ar:
                    raise ValueError(f"model_admission_status accepts no args keys; got {k!r}")
        elif a == "model_admission_acquire":
            if "goal" not in ar or not isinstance(ar.get("goal"), str):
                raise ValueError("model_admission_acquire requires string goal")
            for key in ("prompt", "business_type", "idempotency_key"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"model_admission_acquire {key} must be string")
            if "require_json" in ar and not isinstance(ar.get("require_json"), bool):
                raise ValueError("model_admission_acquire require_json must be boolean")
            if "max_output_tokens" in ar:
                value = ar.get("max_output_tokens")
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("model_admission_acquire max_output_tokens must be positive integer")
            if "lease_ttl_s" in ar:
                _validate_timeout(ar["lease_ttl_s"], label="model_admission_acquire lease_ttl_s")
        elif a == "model_admission_release":
            if "lease_id" not in ar or not isinstance(ar.get("lease_id"), str):
                raise ValueError("model_admission_release requires string lease_id")
        elif a == "model_admission_renew":
            if "lease_id" not in ar or not isinstance(ar.get("lease_id"), str):
                raise ValueError("model_admission_renew requires string lease_id")
            if "lease_ttl_s" in ar:
                _validate_timeout(ar["lease_ttl_s"], label="model_admission_renew lease_ttl_s")
        elif a == "enterprise_stack_plan":
            if "goal" not in ar or not isinstance(ar.get("goal"), str):
                raise ValueError("enterprise_stack_plan requires string goal")
            for key in ("scale", "provider"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"enterprise_stack_plan {key} must be string")
            if "regulated" in ar and not isinstance(ar.get("regulated"), bool):
                raise ValueError("enterprise_stack_plan regulated must be boolean")
        elif a == "distributed_platform_plan":
            if ar:
                for k in ar:
                    raise ValueError(f"distributed_platform_plan accepts no args keys; got {k!r}")
        elif a == "distributed_workload_catalog":
            if ar:
                for k in ar:
                    raise ValueError(f"distributed_workload_catalog accepts no args keys; got {k!r}")
        elif a == "distributed_job_plan":
            for key in ("job_id", "workload"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"distributed_job_plan requires string {key}")
            for key in ("entrypoint", "backend", "source_manifest_id", "queue"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"distributed_job_plan {key} must be string")
            if "resources" in ar and not isinstance(ar.get("resources"), dict):
                raise ValueError("distributed_job_plan resources must be object")
        elif a == "project_model_program_plan":
            if "ambition" in ar and not isinstance(ar.get("ambition"), str):
                raise ValueError("project_model_program_plan ambition must be string")
            if "target_context_tokens" in ar:
                value = ar.get("target_context_tokens")
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("project_model_program_plan target_context_tokens must be positive integer")
        elif a == "github_corpus_program_plan":
            if ar:
                for k in ar:
                    raise ValueError(f"github_corpus_program_plan accepts no args keys; got {k!r}")
        elif a == "github_query_plan_build":
            value = ar.get("seed_queries")
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError("github_query_plan_build requires seed_queries string array")
            if "web_results" in ar and not isinstance(ar.get("web_results"), list):
                raise ValueError("github_query_plan_build web_results must be array")
            if "strategy" in ar and not isinstance(ar.get("strategy"), dict):
                raise ValueError("github_query_plan_build strategy must be object")
            if "max_queries" in ar:
                value = ar.get("max_queries")
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("github_query_plan_build max_queries must be positive integer")
        elif a == "github_candidate_rank":
            if "query" not in ar or not isinstance(ar.get("query"), str):
                raise ValueError("github_candidate_rank requires string query")
            if "profiles" not in ar or not isinstance(ar.get("profiles"), list):
                raise ValueError("github_candidate_rank requires profiles array")
            if "web_results" in ar and not isinstance(ar.get("web_results"), list):
                raise ValueError("github_candidate_rank web_results must be array")
            if "feedback_by_tag" in ar and not isinstance(ar.get("feedback_by_tag"), dict):
                raise ValueError("github_candidate_rank feedback_by_tag must be object")
            if "strategy" in ar and not isinstance(ar.get("strategy"), dict):
                raise ValueError("github_candidate_rank strategy must be object")
            if "allowed_licenses" in ar:
                value = ar.get("allowed_licenses")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("github_candidate_rank allowed_licenses must be string array")
            if "min_quality" in ar and not isinstance(ar.get("min_quality"), (int, float)):
                raise ValueError("github_candidate_rank min_quality must be number")
        elif a == "corpus_feedback_plan":
            if "ranking" not in ar or not isinstance(ar.get("ranking"), dict):
                raise ValueError("corpus_feedback_plan requires object ranking")
            if "downstream_metrics" in ar and not isinstance(ar.get("downstream_metrics"), dict):
                raise ValueError("corpus_feedback_plan downstream_metrics must be object")
            if "target_train_now_rate" in ar and not isinstance(ar.get("target_train_now_rate"), (int, float)):
                raise ValueError("corpus_feedback_plan target_train_now_rate must be number")
        elif a in {"github_corpus_scheduler_plan", "github_corpus_scheduler_cycle"}:
            if "output_root" not in ar or not isinstance(ar.get("output_root"), str):
                raise ValueError(f"{a} requires string output_root")
            value = ar.get("seed_queries")
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError(f"{a} requires seed_queries string array")
            if "github" in ar and not isinstance(ar.get("github"), bool):
                raise ValueError(f"{a} github must be boolean")
            for key in ("local_repos", "allowed_licenses"):
                if key in ar:
                    value = ar.get(key)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        raise ValueError(f"{a} {key} must be string array")
            if "web_results" in ar and not isinstance(ar.get("web_results"), list):
                raise ValueError(f"{a} web_results must be array")
            if "downstream_metrics" in ar and not isinstance(ar.get("downstream_metrics"), dict):
                raise ValueError(f"{a} downstream_metrics must be object")
            for key in ("interval_seconds", "repo_limit", "max_query_arms", "min_stars", "cpu_thread_budget", "max_cycles_retained"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError(f"{a} {key} must be non-negative integer")
            if "quality_threshold" in ar:
                value = ar.get("quality_threshold")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError(f"{a} quality_threshold must be finite number")
            if "updated_after" in ar and not isinstance(ar.get("updated_after"), str):
                raise ValueError(f"{a} updated_after must be string")
            if "force" in ar and not isinstance(ar.get("force"), bool):
                raise ValueError(f"{a} force must be boolean")
        elif a == "github_corpus_flywheel_cycle":
            if "output_root" not in ar or not isinstance(ar.get("output_root"), str):
                raise ValueError("github_corpus_flywheel_cycle requires string output_root")
            value = ar.get("seed_queries")
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError("github_corpus_flywheel_cycle requires seed_queries string array")
            if "github" in ar and not isinstance(ar.get("github"), bool):
                raise ValueError("github_corpus_flywheel_cycle github must be boolean")
            for key in ("local_repos", "allowed_licenses"):
                if key in ar:
                    value = ar.get(key)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        raise ValueError(f"github_corpus_flywheel_cycle {key} must be string array")
            if "web_results" in ar and not isinstance(ar.get("web_results"), list):
                raise ValueError("github_corpus_flywheel_cycle web_results must be array")
            if "downstream_metrics" in ar and not isinstance(ar.get("downstream_metrics"), dict):
                raise ValueError("github_corpus_flywheel_cycle downstream_metrics must be object")
            for key in (
                "downstream_metrics_path",
                "predictions_path",
                "baseline_report_path",
                "updated_after",
            ):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"github_corpus_flywheel_cycle {key} must be string")
            for key in (
                "interval_seconds",
                "repo_limit",
                "max_query_arms",
                "min_stars",
                "cpu_thread_budget",
                "max_cycles_retained",
                "max_repos",
                "max_files",
                "max_slices",
                "max_symbol_examples_per_repo",
            ):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError(f"github_corpus_flywheel_cycle {key} must be non-negative integer")
            if "quality_threshold" in ar:
                value = ar.get("quality_threshold")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError("github_corpus_flywheel_cycle quality_threshold must be finite number")
            if "force" in ar and not isinstance(ar.get("force"), bool):
                raise ValueError("github_corpus_flywheel_cycle force must be boolean")
        elif a in {"github_corpus_projectization_plan", "github_corpus_projectize"}:
            for key in ("crawl_output_dir", "output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"{a} requires string {key}")
            if "allowed_routes" in ar:
                value = ar.get("allowed_routes")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError(f"{a} allowed_routes must be string array")
            for key in ("max_repos", "max_files", "max_slices", "max_symbol_examples_per_repo"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError(f"{a} {key} must be non-negative integer")
        elif a == "github_corpus_training_bundle":
            for key in ("projectization_dir", "output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"github_corpus_training_bundle requires string {key}")
            if "include_routes" in ar:
                value = ar.get("include_routes")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("github_corpus_training_bundle include_routes must be string array")
            for key in ("dataset_format", "model_hint"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"github_corpus_training_bundle {key} must be string")
            if "eval_ratio" in ar and not isinstance(ar.get("eval_ratio"), (int, float)):
                raise ValueError("github_corpus_training_bundle eval_ratio must be number")
            for key in ("min_chars", "max_examples", "protocol_example_limit"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError(f"github_corpus_training_bundle {key} must be non-negative integer")
            for key in ("include_protocol_examples", "prepare_dataset"):
                if key in ar and not isinstance(ar.get(key), bool):
                    raise ValueError(f"github_corpus_training_bundle {key} must be boolean")
        elif a == "project_repo_memory_build":
            for key in ("repo_path", "output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"project_repo_memory_build requires string {key}")
            for key in ("max_files", "max_slices"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                        raise ValueError(f"project_repo_memory_build {key} must be positive integer")
        elif a == "project_holdout_benchmark_build":
            for key in ("projectization_dir", "output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"project_holdout_benchmark_build requires string {key}")
        elif a == "project_holdout_evaluate":
            for key in ("benchmark_path", "predictions_path", "output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"project_holdout_evaluate requires string {key}")
            if "baseline_report_path" in ar and not isinstance(ar.get("baseline_report_path"), str):
                raise ValueError("project_holdout_evaluate baseline_report_path must be string")
        elif a == "github_corpus_status":
            if "output_root" not in ar or not isinstance(ar.get("output_root"), str):
                raise ValueError("github_corpus_status requires string output_root")
        elif a == "project_task_synthesis_build":
            if "output_dir" not in ar or not isinstance(ar.get("output_dir"), str):
                raise ValueError("project_task_synthesis_build requires string output_dir")
            value = ar.get("memory_dirs")
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ValueError("project_task_synthesis_build memory_dirs must be string array")
            if "max_symbol_examples_per_repo" in ar:
                limit = ar.get("max_symbol_examples_per_repo")
                if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                    raise ValueError("project_task_synthesis_build max_symbol_examples_per_repo must be positive integer")
        elif a == "training_platform_blueprint":
            if ar:
                for k in ar:
                    raise ValueError(f"training_platform_blueprint accepts no args keys; got {k!r}")
        elif a == "training_recipe_plan":
            for key in ("name", "research_question", "base_model", "objective"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"training_recipe_plan requires string {key}")
            for key in ("task_mix", "data_mix", "teacher_mix", "method", "knobs"):
                if key in ar and not isinstance(ar.get(key), dict):
                    raise ValueError(f"training_recipe_plan {key} must be object")
            if "evaluation_suite" in ar:
                value = ar.get("evaluation_suite")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("training_recipe_plan evaluation_suite must be string array")
            if "notes" in ar and not isinstance(ar.get("notes"), str):
                raise ValueError("training_recipe_plan notes must be string")
        elif a == "ablation_plan_build":
            for key in ("name", "research_question"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"ablation_plan_build requires string {key}")
            if not isinstance(ar.get("baseline_recipe"), dict):
                raise ValueError("ablation_plan_build requires object baseline_recipe")
            value = ar.get("variants")
            if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
                raise ValueError("ablation_plan_build variants must be object array")
            for key in ("primary_metrics", "success_criteria"):
                arr = ar.get(key)
                if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
                    raise ValueError(f"ablation_plan_build {key} must be string array")
        elif a == "teacher_registry":
            if ar:
                for k in ar:
                    raise ValueError(f"teacher_registry accepts no args keys; got {k!r}")
        elif a == "teacher_task_suite_plan":
            if "name" not in ar or not isinstance(ar.get("name"), str):
                raise ValueError("teacher_task_suite_plan requires string name")
            if "task_mix" in ar and not isinstance(ar.get("task_mix"), dict):
                raise ValueError("teacher_task_suite_plan task_mix must be object")
            if "evidence_policy" in ar and not isinstance(ar.get("evidence_policy"), str):
                raise ValueError("teacher_task_suite_plan evidence_policy must be string")
        elif a == "distillation_plan_build":
            for key in ("name", "student_model"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"distillation_plan_build requires string {key}")
            if not isinstance(ar.get("teacher_mix"), dict):
                raise ValueError("distillation_plan_build requires object teacher_mix")
            if not isinstance(ar.get("task_suite"), dict):
                raise ValueError("distillation_plan_build requires object task_suite")
            for key in ("target_recipe_id", "consensus_policy", "output_policy"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"distillation_plan_build {key} must be string")
            if "acceptance_thresholds" in ar and not isinstance(ar.get("acceptance_thresholds"), dict):
                raise ValueError("distillation_plan_build acceptance_thresholds must be object")
        elif a == "distillation_dataset_manifest_build":
            if not isinstance(ar.get("distillation_plan"), dict):
                raise ValueError("distillation_dataset_manifest_build requires object distillation_plan")
            value = ar.get("teacher_outputs")
            if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
                raise ValueError("distillation_dataset_manifest_build teacher_outputs must be object array")
        elif a == "teacher_prompt_batch_build":
            if not isinstance(ar.get("distillation_plan"), dict):
                raise ValueError("teacher_prompt_batch_build requires object distillation_plan")
            value = ar.get("source_examples")
            if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
                raise ValueError("teacher_prompt_batch_build source_examples must be object array")
            if "max_prompts" in ar:
                value = ar.get("max_prompts")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("teacher_prompt_batch_build max_prompts must be non-negative integer")
        elif a == "teacher_execution_plan_build":
            if not isinstance(ar.get("distillation_plan"), dict):
                raise ValueError("teacher_execution_plan_build requires object distillation_plan")
            if not isinstance(ar.get("prompt_batch"), dict):
                raise ValueError("teacher_execution_plan_build requires object prompt_batch")
            if "mode" in ar and not isinstance(ar.get("mode"), str):
                raise ValueError("teacher_execution_plan_build mode must be string")
            if "allow_remote" in ar and not isinstance(ar.get("allow_remote"), bool):
                raise ValueError("teacher_execution_plan_build allow_remote must be boolean")
            if "max_prompts" in ar:
                value = ar.get("max_prompts")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("teacher_execution_plan_build max_prompts must be non-negative integer")
            if "max_output_tokens" in ar:
                value = ar.get("max_output_tokens")
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("teacher_execution_plan_build max_output_tokens must be positive integer")
            if "temperature" in ar and (isinstance(ar.get("temperature"), bool) or not isinstance(ar.get("temperature"), (int, float))):
                raise ValueError("teacher_execution_plan_build temperature must be number")
        elif a == "teacher_execution_run":
            if not isinstance(ar.get("execution_plan"), dict):
                raise ValueError("teacher_execution_run requires object execution_plan")
            if "timeout" in ar:
                _validate_timeout(ar["timeout"], label="teacher_execution_run timeout")
            if "max_retries" in ar:
                value = ar.get("max_retries")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("teacher_execution_run max_retries must be non-negative integer")
        elif a == "teacher_output_review_build":
            if not isinstance(ar.get("distillation_plan"), dict):
                raise ValueError("teacher_output_review_build requires object distillation_plan")
            if not isinstance(ar.get("prompt_batch"), dict):
                raise ValueError("teacher_output_review_build requires object prompt_batch")
            value = ar.get("teacher_outputs")
            if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
                raise ValueError("teacher_output_review_build teacher_outputs must be object array")
        elif a == "distillation_export_build":
            if "output_dir" not in ar or not isinstance(ar.get("output_dir"), str):
                raise ValueError("distillation_export_build requires string output_dir")
            if not isinstance(ar.get("distillation_plan"), dict):
                raise ValueError("distillation_export_build requires object distillation_plan")
            if not isinstance(ar.get("teacher_output_review"), dict):
                raise ValueError("distillation_export_build requires object teacher_output_review")
        elif a == "first_training_round_plan":
            for key in ("name", "training_output_dir", "model_output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"first_training_round_plan requires string {key}")
            for key in ("learning_dirs", "solution_dirs"):
                if key in ar:
                    value = ar.get(key)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        raise ValueError(f"first_training_round_plan {key} must be string array")
            for key in ("base_model", "dataset_format", "notes"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"first_training_round_plan {key} must be string")
            if "include_protocol_examples" in ar and not isinstance(ar.get("include_protocol_examples"), bool):
                raise ValueError("first_training_round_plan include_protocol_examples must be boolean")
            for key in ("eval_ratio",):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError(f"first_training_round_plan {key} must be number")
            for key in ("min_chars", "max_examples", "protocol_example_limit", "min_train_examples"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError(f"first_training_round_plan {key} must be non-negative integer")
        elif a == "training_server_preflight":
            if "policy" in ar and not isinstance(ar.get("policy"), dict):
                raise ValueError("training_server_preflight policy must be object")
        elif a == "industrial_maturity_plan":
            if "goal" not in ar or not isinstance(ar.get("goal"), str):
                raise ValueError("industrial_maturity_plan requires string goal")
            for key in ("scale", "provider"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"industrial_maturity_plan {key} must be string")
            if "regulated" in ar and not isinstance(ar.get("regulated"), bool):
                raise ValueError("industrial_maturity_plan regulated must be boolean")
        elif a == "enterprise_readiness_check":
            if ar:
                for k in ar:
                    raise ValueError(f"enterprise_readiness_check accepts no args keys; got {k!r}")
        elif a == "workflow_validate":
            if "spec" not in ar or not isinstance(ar.get("spec"), dict):
                raise ValueError("workflow_validate requires object spec")
        elif a == "innovation_radar":
            if "roots" in ar:
                value = ar.get("roots")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("innovation_radar roots must be string array")
        elif a == "intent_compile":
            if "goal" not in ar or not isinstance(ar.get("goal"), str):
                raise ValueError("intent_compile requires string goal")
            if "roots" in ar:
                value = ar.get("roots")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("intent_compile roots must be string array")
        elif a == "workflow_dry_run":
            if "spec" not in ar or not isinstance(ar.get("spec"), dict):
                raise ValueError("workflow_dry_run requires object spec")
        elif a == "evidence_ledger":
            if "roots" in ar:
                value = ar.get("roots")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("evidence_ledger roots must be string array")
            if "output_path" in ar and not isinstance(ar.get("output_path"), str):
                raise ValueError("evidence_ledger output_path must be string")
        elif a == "research_feedback_report":
            if "roots" in ar:
                value = ar.get("roots")
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    raise ValueError("research_feedback_report roots must be string array")
            if "output_path" in ar and not isinstance(ar.get("output_path"), str):
                raise ValueError("research_feedback_report output_path must be string")
            if "low_score_threshold" in ar:
                value = ar.get("low_score_threshold")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError("research_feedback_report low_score_threshold must be finite number")
        elif a == "solution_publish":
            for key in ("output_dir", "title", "source_type"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"solution_publish {key} must be string")
        elif a == "research_synthesize":
            if "query" not in ar or not isinstance(ar.get("query"), str):
                raise ValueError("research_synthesize requires string query")
            if "top_k" in ar:
                top_k = ar.get("top_k")
                if not isinstance(top_k, int) or top_k < 1:
                    raise ValueError("research_synthesize top_k must be positive integer")
            for key in ("use_web", "use_llm", "use_cache", "refresh_cache"):
                if key in ar and not isinstance(ar.get(key), bool):
                    raise ValueError(f"research_synthesize {key} must be boolean")
            if "cache_ttl_seconds" in ar:
                value = ar.get("cache_ttl_seconds")
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError("research_synthesize cache_ttl_seconds must be positive integer")
            for key in ("web_provider", "llm_provider", "llm_model"):
                if key in ar and ar.get(key) is not None and not isinstance(ar.get(key), str):
                    raise ValueError(f"research_synthesize {key} must be string")
            for key in ("solution_dirs", "learning_dirs"):
                if key in ar:
                    value = ar.get(key)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        raise ValueError(f"research_synthesize {key} must be string array")
        elif a == "training_prepare":
            if "output_dir" not in ar or not isinstance(ar.get("output_dir"), str):
                raise ValueError("training_prepare requires string output_dir")
            if "dataset_format" in ar and not isinstance(ar.get("dataset_format"), str):
                raise ValueError("training_prepare dataset_format must be string")
            if "model_hint" in ar and not isinstance(ar.get("model_hint"), str):
                raise ValueError("training_prepare model_hint must be string")
            if "include_protocol_examples" in ar and not isinstance(ar.get("include_protocol_examples"), bool):
                raise ValueError("training_prepare include_protocol_examples must be boolean")
            for key in ("learning_dirs", "solution_dirs"):
                if key in ar:
                    value = ar.get(key)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        raise ValueError(f"training_prepare {key} must be string array")
            if "eval_ratio" in ar:
                ratio = ar.get("eval_ratio")
                if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(float(ratio)):
                    raise ValueError("training_prepare eval_ratio must be finite number")
            for key in ("min_chars", "max_examples"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                        raise ValueError(f"training_prepare {key} must be positive integer")
            if "protocol_example_limit" in ar:
                value = ar.get("protocol_example_limit")
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError("training_prepare protocol_example_limit must be non-negative integer")
        elif a == "backup_model_train":
            for key in ("training_dir", "output_dir"):
                if key not in ar or not isinstance(ar.get(key), str):
                    raise ValueError(f"backup_model_train requires string {key}")
            for key in ("base_model", "adapter_name", "trainer_backend", "target_modules"):
                if key in ar and not isinstance(ar.get(key), str):
                    raise ValueError(f"backup_model_train {key} must be string")
            if "launch" in ar and not isinstance(ar.get("launch"), bool):
                raise ValueError("backup_model_train launch must be boolean")
            for key in ("min_quality_score", "learning_rate", "epochs", "lora_dropout"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                        raise ValueError(f"backup_model_train {key} must be finite number")
            for key in (
                "min_train_examples",
                "max_seq_length",
                "per_device_train_batch_size",
                "gradient_accumulation_steps",
                "lora_r",
                "lora_alpha",
            ):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                        raise ValueError(f"backup_model_train {key} must be positive integer")
        elif a == "github_crawl_profile":
            if "output_dir" not in ar or not isinstance(ar.get("output_dir"), str):
                raise ValueError("github_crawl_profile requires string output_dir")
            if "query" in ar and not isinstance(ar.get("query"), str):
                raise ValueError("github_crawl_profile query must be string")
            if "github" in ar and not isinstance(ar.get("github"), bool):
                raise ValueError("github_crawl_profile github must be boolean")
            for key in ("local_repos", "allowed_licenses", "seed_queries"):
                if key in ar:
                    value = ar.get(key)
                    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                        raise ValueError(f"github_crawl_profile {key} must be string array")
            if "web_results" in ar and not isinstance(ar.get("web_results"), list):
                raise ValueError("github_crawl_profile web_results must be array")
            for key in ("repo_limit", "min_stars", "max_query_arms"):
                if key in ar:
                    value = ar.get(key)
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError(f"github_crawl_profile {key} must be non-negative integer")
            if "quality_threshold" in ar:
                value = ar.get("quality_threshold")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ValueError("github_crawl_profile quality_threshold must be finite number")
            if "updated_after" in ar and not isinstance(ar.get("updated_after"), str):
                raise ValueError("github_crawl_profile updated_after must be string")
            if "downstream_metrics" in ar and not isinstance(ar.get("downstream_metrics"), dict):
                raise ValueError("github_crawl_profile downstream_metrics must be object")
            if "strategy" in ar and not isinstance(ar.get("strategy"), dict):
                raise ValueError("github_crawl_profile strategy must be object")
        return self

    def to_executor_dict(self) -> dict[str, Any]:
        return {"type": "action", "action": self.action, "args": dict(self.args)}


class ProtocolError(ValueError):
    pass


def _validate_timeout(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be number")
    timeout = float(value)
    if not math.isfinite(timeout):
        raise ValueError(f"{label} must be finite")
    if timeout <= 0:
        raise ValueError(f"{label} must be positive")


#_ 清洗 extract_json_object()
def _extract_json_object(text: str) -> str:
    """从模型偶尔包裹的 ```json ... ``` 或前后噪声中抽出第一个 JSON 对象。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ProtocolError("no json object found in model output")
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ProtocolError("no complete json object found in model output")

#主入口
def parse_and_validate_action_line(line: str) -> dict[str, Any]:
    line = line.strip()
    if not line:
        raise ProtocolError("empty action line")
    #尝试直接 JSON 解析
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        #清洗后重试
        try:
            raw = json.loads(_extract_json_object(line))
        except (json.JSONDecodeError, ProtocolError) as e:
            raise ProtocolError(f"invalid json: {e}") from e
    ## Step 3: 类型检查
    if isinstance(raw, list):
        raise ProtocolError("action must be a single object, not array")
    #Step 4: Pydantic 强校验
    if not isinstance(raw, dict):
        raise ProtocolError("action must be a json object")
    try:
        dto = ActionDTO.model_validate(raw)
    except ValidationError as e:
        raise ProtocolError(str(e)) from e
    ## Step 5: 输出干净字典
    return dto.to_executor_dict()

    #二次校验 ---生成执行器可用的干净字典
def validate_action_dict(obj: dict[str, Any]) -> dict[str, Any]:
    try:
        dto = ActionDTO.model_validate(obj)
    except ValidationError as e:
        raise ProtocolError(str(e)) from e
    return dto.to_executor_dict()
