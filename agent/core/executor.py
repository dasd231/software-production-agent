"""Action 执行器 — 唯一入口；协议校验、限额、合并策略黑名单。

函数流程图：
    run(action_json_line)
      -> parse_action()
        -> parse_and_validate_action_line()  # JSON + 协议层校验
      -> run_action()
        -> validate_action_dict()            # dict 再校验，防止绕过 parse
        -> _require()                        # 强制字段提取
        -> 按 action 分发：
             write_file       -> 写入大小限制 -> file_tools.write_file()
             read_file        -> file_tools.read_file()
             list_files       -> file_tools.list_files()
             run_command      -> 命令策略黑名单 -> _resolve_timeout() -> run_shell() -> _clip_command_output()
             git_status/init  -> git_tools
             workspace_index  -> build_workspace_index()
             mcp_capabilities -> default_mcp_capabilities()
             production_check -> _resolve_timeout() -> run_production_checks()
             mcp_call         -> invoke_mcp_tool()
             integration_catalog -> third-party embedded surface catalog
             integration_embed_plan -> embed, bridge and permission plan
             model_runtime_status -> provider runtime metadata and health probe
             model_admission_* -> high-concurrency model-pool leases and backpressure
             model_route_plan -> token estimate, pool selection and admission plan
             enterprise_stack_plan -> enterprise stack, hot iteration and model plane plan
             industrial_maturity_plan -> safety-critical maturity assessment and roadmap
             enterprise_readiness_check -> static production readiness gates
             intent_compile    -> goal -> workflow + validation + dry-run
             workflow_dry_run  -> workflow -> execution order and gates
             evidence_ledger   -> manifests/reports/events -> evidence ledger
             solution_publish  -> run workspace -> reusable solution asset
             research_synthesize -> local solution library + RAG + optional Web/LLM
             training_prepare -> fine-tuning dataset preparation
             github_crawl_profile -> GitHub/local frontend-backend profiler
             finish           -> 返回完成原因

你可以继续练算法/工程化的点：
    1. 动作分发：现在是 if 链；可以改成 registry/dispatch table，比较可维护性。
    2. 参数校验：现在分散在协议层和执行层；可以抽象成 per-action schema。
    3. 超时策略：现在是固定上限；可以按动作风险、历史失败次数、文件规模动态调度。
    4. 结果裁剪：现在是 head+tail 保留；可以改成按错误栈、测试失败块、关键词评分来摘要。
    5. 工具选择：mcp_call 现在直接调用；可以加工具评分/重试/降级策略。
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
"""
    将 LLM 生成的结构化动作指令转换为实际的系统操作
    同时承担协议校验、安全限额、命令策略黑名单三重职责。
"""
from agent.core.governance import build_preflight_report
from agent.core.protocol import ProtocolError, parse_and_validate_action_line, validate_action_dict
from agent.chains.github_crawler import CrawlProfileInput, crawl_frontend_backend_repos
from agent.chains.model_training import BackupModelTrainInput, prepare_backup_model_training
from agent.chains.registry import get_chain, list_chains
from agent.chains.research import ResearchChainInput, run_research_chain
from agent.chains.training import TrainingPrepareInput, prepare_fine_tuning_dataset
from agent.corpus_intelligence.feedback import build_corpus_feedback_report
from agent.corpus_intelligence.flywheel import CorpusFlywheelInput, run_corpus_flywheel_cycle
from agent.corpus_intelligence.program import build_github_corpus_program
from agent.corpus_intelligence.projectization import (
    CorpusProjectizationInput,
    build_corpus_projectization_plan,
    materialize_corpus_projectization,
)
from agent.corpus_intelligence.ranking import build_github_query_plan, rank_repo_profiles
from agent.corpus_intelligence.scheduler import (
    CorpusSchedulerConfig,
    build_corpus_scheduler_plan,
    run_corpus_scheduler_cycle,
)
from agent.corpus_intelligence.status import build_corpus_flywheel_status
from agent.corpus_intelligence.training_bundle import CorpusTrainingBundleInput, build_corpus_training_bundle
from agent.evidence.ledger import build_evidence_ledger
from agent.enterprise.stack import build_enterprise_stack_plan
from agent.distillation.catalog import list_teacher_models, list_teacher_tasks
from agent.distillation.datasets import build_distillation_dataset_manifest
from agent.distillation.execution import build_teacher_execution_plan
from agent.distillation.export import export_distillation_training_examples
from agent.distillation.plans import build_distillation_plan, build_teacher_task_suite
from agent.distillation.prompts import build_teacher_prompt_batch
from agent.distillation.review import review_teacher_outputs
from agent.distillation.runtime import run_teacher_execution
from agent.distributed.plans import build_distributed_platform_plan
from agent.distributed.dispatch import build_distributed_job_plan
from agent.distributed.workloads import list_distributed_workloads
from agent.enterprise.maturity import build_industrial_maturity_plan
from agent.enterprise.readiness import build_enterprise_readiness_report
from agent.innovation.radar import build_innovation_radar
from agent.intent.compiler import compile_intent
from agent.integrations.embedding import build_integration_embed_plan, list_integration_catalog
from agent.llm.runtime import model_runtime_status
from agent.learning.web_search import search_web
from agent.mcp.adapter import default_mcp_capabilities, invoke_mcp_tool
from agent.policies.loader import CommandPolicyError, assert_command_policy
from agent.project_model.program import build_project_model_program
from agent.project_model.holdout_benchmark import (
    ProjectHoldoutBenchmarkBuildInput,
    ProjectHoldoutEvaluationInput,
    build_project_holdout_benchmark,
    evaluate_project_holdout,
)
from agent.project_model.repo_memory import RepoMemoryBuildInput, build_repo_memory
from agent.project_model.task_synthesis import ProjectTaskSynthesisInput, synthesize_project_tasks
from agent.software_middle_model import MiddleModelInput, build_software_middle_model_plan, decide_with_middle_model
from agent.training.studio import (
    build_ablation_plan,
    build_training_platform_blueprint,
    build_training_recipe,
)
from agent.training.rounds import build_first_training_round_plan
from agent.training.resource_guard import build_training_resource_policy, run_server_resource_preflight
from agent.resources.registry import discover_resources
from agent.runtime.production_check import run_production_checks
from agent.scheduler.admission import get_global_admission_controller
from agent.scheduler.routing import build_model_route_plan
from agent.solution_library.publish import publish_solution_from_run
from agent.evaluation.feedback import build_research_feedback_report
from agent.tools import file_tools
from agent.tools import git_tools
from agent.tools.workspace_index import build_workspace_index
from agent.tools.shell_tools import run_shell
from agent.workflows.dry_run import dry_run_workflow
from agent.workflows.spec import validate_workflow_spec

#执行限额配置
class ExecutorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionLimits:
    max_write_bytes: int = 1_500_000
    default_command_timeout: float = 120.0
    max_command_timeout: float = 600.0
    max_command_output_chars: int = 200_000
    policy_extra_path: Path | None = None
    granted_permissions: frozenset[str] = frozenset({"*"})
    confirmed_actions: frozenset[str] = frozenset()

#强制字段提取
def _require(obj: dict[str, Any], key: str) -> Any:
    if key not in obj:
        raise ExecutorError(f"missing field: {key}")
    return obj[key]


def _resolve_timeout(raw: Any, limits: ExecutionLimits) -> float:
    try:
        timeout = limits.default_command_timeout if raw is None else float(raw)
    except (TypeError, ValueError) as e:
        raise ExecutorError("timeout must be number") from e
    if not math.isfinite(timeout):
        raise ExecutorError("timeout must be finite")
    if timeout <= 0:
        raise ExecutorError("timeout must be positive")
    if limits.max_command_timeout > 0:
        timeout = min(timeout, limits.max_command_timeout)
    return timeout


def _clip_text_middle(text: str, limit: int) -> tuple[str, bool]:
    if limit <= 0:
        return "", bool(text)
    if len(text) <= limit:
        return text, False
    marker = "\n...[truncated]...\n"
    if len(marker) >= limit:
        return text[:limit], True
    keep = limit - len(marker)
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:], True


def _feedback_block(command: str, cwd: Path | str, returncode: int, stdout: str, stderr: str) -> str:
    parts = [
        f"command: {command}",
        f"cwd: {cwd}",
        f"returncode: {returncode}",
    ]
    if stdout.strip():
        parts.append("--- stdout ---\n" + stdout)
    if stderr.strip():
        parts.append("--- stderr ---\n" + stderr)
    return "\n".join(parts)


def _clip_command_output(result: Any, limits: ExecutionLimits) -> dict[str, Any]:
    stdout, stdout_truncated = _clip_text_middle(str(getattr(result, "stdout", "") or ""), limits.max_command_output_chars)
    stderr, stderr_truncated = _clip_text_middle(str(getattr(result, "stderr", "") or ""), limits.max_command_output_chars)
    command = str(getattr(result, "command", ""))
    cwd = str(getattr(result, "cwd", ""))
    returncode = int(getattr(result, "returncode", -1))
    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "feedback": _feedback_block(command, cwd, returncode, stdout, stderr),
    }


def _string_tuple_arg(args: dict[str, Any], key: str) -> tuple[str, ...]:
    value = args.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(str(x) for x in value if str(x).strip())


def _path_tuple_arg(args: dict[str, Any], key: str) -> tuple[Path, ...]:
    return tuple(Path(x) for x in _string_tuple_arg(args, key))


def _optional_path_arg(workspace: Path, args: dict[str, Any], key: str) -> Path | None:
    raw = str(args.get(key, "") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def parse_action(line: str) -> dict[str, Any]:
    try:
        return parse_and_validate_action_line(line)
    except ProtocolError as e:
        raise ExecutorError(str(e)) from e


def _duration_ms(started_at: float) -> float:
    return round(max(0.0, time.perf_counter() - started_at) * 1000.0, 3)


def _error_envelope(
    *,
    action: str,
    error_code: str,
    error: str,
    retryable: bool,
    recommended_action: str,
    preflight: dict[str, Any],
    duration_ms: float,
) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "error_code": error_code,
        "error": error,
        "retryable": retryable,
        "recommended_action": recommended_action,
        "preflight": preflight,
        "duration_ms": duration_ms,
    }


def _classify_exception(exc: Exception) -> tuple[str, bool, str]:
    message = str(exc).lower()
    if isinstance(exc, ProtocolError):
        return "VALIDATION_ERROR", False, "revise_action_schema"
    if "blocked" in message:
        return "POLICY_BLOCKED", False, "choose_allowed_action"
    if "permission" in message:
        return "PERMISSION_DENIED", False, "request_permission_or_use_allowed_action"
    return "INTERNAL_ERROR", False, "inspect_executor_error"


def _classify_failed_result(result: dict[str, Any]) -> tuple[str, bool, str]:
    action = str(result.get("action", ""))
    stderr = str(result.get("stderr", "") or "").lower()
    error = str(result.get("error", "") or "").lower()
    if action == "run_command" and (
        int(result.get("returncode", 0) or 0) == -1 or "[timeout]" in stderr or "timed out" in stderr
    ):
        return "TIMEOUT", True, "retry_with_narrower_scope_or_longer_timeout"
    if "permission" in stderr or "permission" in error:
        return "PERMISSION_DENIED", False, "request_permission_or_use_allowed_action"
    return "TOOL_FAILURE", action in {"run_command", "web_search", "mcp_call"}, "inspect_result_or_use_fallback"


def run_action_guarded(
    workspace: Path,
    action_obj: dict[str, Any],
    limits: ExecutionLimits | None = None,
) -> dict[str, Any]:
    """Execute with preflight, standard error codes and timing metadata."""

    lim = limits or ExecutionLimits()
    started = time.perf_counter()
    action_name = str(action_obj.get("action", ""))
    try:
        validated = validate_action_dict(action_obj)
        action_name = str(validated.get("action", ""))
        args = validated.get("args") if isinstance(validated.get("args"), dict) else {}
        preflight = build_preflight_report(
            action_name,
            args,
            granted_permissions=lim.granted_permissions,
            confirmed_actions=lim.confirmed_actions,
        )
        if not preflight["allowed"]:
            code = str(preflight.get("error_code") or "PERMISSION_DENIED")
            recommended = (
                "request_explicit_confirmation"
                if code == "CONFIRMATION_REQUIRED"
                else "request_permission_or_use_allowed_action"
            )
            return _error_envelope(
                action=action_name,
                error_code=code,
                error=str(preflight.get("status", "preflight_denied")),
                retryable=False,
                recommended_action=recommended,
                preflight=preflight,
                duration_ms=_duration_ms(started),
            )
        result = dict(run_action(workspace, validated, limits=lim))
        result["preflight"] = preflight
        result["duration_ms"] = _duration_ms(started)
        if not bool(result.get("ok", False)):
            code, retryable, recommended = _classify_failed_result(result)
            result.setdefault("error_code", code)
            result.setdefault("retryable", retryable)
            result.setdefault("recommended_action", recommended)
        return result
    except Exception as exc:
        code, retryable, recommended = _classify_exception(exc)
        preflight = {
            "allowed": False,
            "status": "validation_error" if code == "VALIDATION_ERROR" else "executor_error",
            "error_code": code,
        }
        return _error_envelope(
            action=action_name,
            error_code=code,
            error=str(exc),
            retryable=retryable,
            recommended_action=recommended,
            preflight=preflight,
            duration_ms=_duration_ms(started),
        )


def run_action(workspace: Path, action_obj: dict[str, Any], limits: ExecutionLimits | None = None) -> dict[str, Any]:
    lim = limits or ExecutionLimits()
    try:
        action_obj = validate_action_dict(action_obj)
    except ProtocolError as e:
        raise ExecutorError(str(e)) from e
    name = str(_require(action_obj, "action"))
    args = action_obj.get("args") or {}
    if not isinstance(args, dict):
        raise ExecutorError("args must be object")

    if name == "write_file":
        path = str(_require(args, "path"))
        content = str(_require(args, "content"))
        if len(content.encode("utf-8")) > lim.max_write_bytes:
            raise ExecutorError(f"write_file exceeds max_write_bytes={lim.max_write_bytes}")
        file_tools.write_file(workspace, path, content)
        return {"ok": True, "action": name, "detail": f"wrote {path}", "bytes": len(content.encode("utf-8"))}

    if name == "read_file":
        path = str(_require(args, "path"))
        text = file_tools.read_file(workspace, path)
        return {"ok": True, "action": name, "content": text}

    if name == "list_files":
        pattern = str(args.get("pattern", "**/*"))
        files = file_tools.list_files(workspace, pattern=pattern)
        return {"ok": True, "action": name, "files": files}
    #最危险动作的层层防护
    if name == "run_command":
        cmd = str(_require(args, "command"))
        try:
            assert_command_policy(cmd, lim.policy_extra_path)# ← 策略黑名单
        except CommandPolicyError as e:
            raise ExecutorError(str(e)) from e
        t = _resolve_timeout(args.get("timeout"), lim)
        result = run_shell(cmd, cwd=workspace, timeout=t)## ← workspace 沙箱 + 超时
        output = _clip_command_output(result, lim)
        return {
            "ok": result.ok(),
            "action": name,
            **output,
        }

    if name == "git_status":
        text = git_tools.git_status(workspace)
        return {"ok": True, "action": name, "content": text}

    if name == "git_init":
        info = git_tools.git_init_if_needed(workspace)
        ok = bool(info.get("ok"))
        return {
            "ok": ok,
            "action": name,
            "status": info.get("status"),
            "stdout": info.get("stdout", ""),
            "stderr": info.get("stderr", ""),
            "detail": json.dumps(info, ensure_ascii=False),
        }

    if name == "workspace_index":
        idx = build_workspace_index(workspace)
        return {"ok": True, "action": name, "index": idx}

    if name == "mcp_capabilities":
        caps = default_mcp_capabilities()
        return {"ok": True, "action": name, "capabilities": caps}

    if name == "production_check":
        include_pytest = bool(args.get("include_pytest", True))
        timeout = _resolve_timeout(args.get("timeout"), lim)
        report = run_production_checks(workspace, include_pytest=include_pytest, timeout=timeout)
        return {"ok": bool(report.get("ok")), "action": name, "report": report}
    # 外部工具调用网关
    if name == "mcp_call":
        tool = str(_require(args, "tool"))
        tool_args = args.get("args") or {}
        if not isinstance(tool_args, dict):
            raise ExecutorError("mcp_call args must be object")
        out = invoke_mcp_tool(workspace, tool, tool_args)
        return {"ok": bool(out.get("ok")), "action": name, "tool": tool, "result": out}

    if name == "web_search":
        query = str(_require(args, "query"))
        top_k = int(args.get("top_k", 5))
        provider = str(args.get("provider", "duckduckgo"))
        results = search_web(query, top_k=max(top_k, 1), provider=provider)
        formatted = [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "source": r.source}
            for r in results
        ]
        return {"ok": True, "action": name, "query": query, "results": formatted, "count": len(formatted)}

    if name == "chain_registry":
        chain_name = str(args.get("name", "") or "").strip()
        if chain_name:
            definition = get_chain(chain_name)
            return {
                "ok": bool(definition),
                "action": name,
                "chain": definition.to_dict() if definition else None,
            }
        return {"ok": True, "action": name, "chains": list_chains()}

    if name == "resource_registry":
        resources = discover_resources(
            workspace,
            roots=_path_tuple_arg(args, "roots"),
            type_filter=str(args.get("type", "") or "").strip(),
        )
        return {"ok": True, "action": name, **resources}

    if name == "integration_catalog":
        catalog = list_integration_catalog(str(args.get("category", "") or ""))
        return {"ok": True, "action": name, "catalog": catalog}

    if name == "integration_embed_plan":
        plan = build_integration_embed_plan(
            str(_require(args, "integration_id")),
            resource_url=str(args.get("resource_url", "") or ""),
            mode=str(args.get("mode", "embed_panel") or "embed_panel"),
            workspace_context=str(args.get("workspace_context", "") or ""),
            requested_capabilities=_string_tuple_arg(args, "requested_capabilities"),
        )
        return {"ok": bool(plan.get("admission", {}).get("embeddable")), "action": name, "plan": plan}

    if name == "model_runtime_status":
        status = model_runtime_status(
            str(args.get("provider", "main_deepseek") or "main_deepseek"),
            str(args.get("model", "") or "") or None,
            probe=bool(args.get("probe", True)),
            timeout=_resolve_timeout(args.get("timeout", 2.0), lim),
        )
        return {"ok": bool(status.get("probe", {}).get("ok")) if status.get("probe", {}).get("checked") else True, "action": name, "status": status}

    if name == "model_admission_status":
        status = get_global_admission_controller().snapshot()
        return {"ok": True, "action": name, "status": status}

    if name == "model_admission_acquire":
        admission = get_global_admission_controller().acquire(
            str(_require(args, "goal")),
            prompt=str(args.get("prompt", "") or ""),
            max_output_tokens=int(args["max_output_tokens"]) if "max_output_tokens" in args else None,
            business_type=str(args.get("business_type", "") or ""),
            require_json=bool(args.get("require_json", False)),
            idempotency_key=str(args.get("idempotency_key", "") or ""),
            lease_ttl_s=float(args["lease_ttl_s"]) if "lease_ttl_s" in args else None,
            metadata={"source": "executor_action"},
        )
        return {"ok": bool(admission.get("admitted")), "action": name, "admission": admission}

    if name == "model_admission_release":
        result = get_global_admission_controller().release(str(_require(args, "lease_id")))
        return {"ok": bool(result.get("released")), "action": name, "release": result}

    if name == "model_admission_renew":
        result = get_global_admission_controller().renew(
            str(_require(args, "lease_id")),
            lease_ttl_s=float(args["lease_ttl_s"]) if "lease_ttl_s" in args else None,
        )
        return {"ok": bool(result.get("renewed")), "action": name, "renewal": result}

    if name == "model_route_plan":
        plan = build_model_route_plan(
            str(_require(args, "goal")),
            prompt=str(args.get("prompt", "") or ""),
            max_output_tokens=int(args["max_output_tokens"]) if "max_output_tokens" in args else None,
            business_type=str(args.get("business_type", "") or ""),
            require_json=bool(args.get("require_json", False)),
        )
        return {"ok": bool(plan.get("admission", {}).get("admitted")), "action": name, "plan": plan}

    if name == "software_middle_model_plan":
        plan = build_software_middle_model_plan(str(args.get("target", "rule_acceleration") or "rule_acceleration"))
        return {"ok": True, "action": name, "plan": plan}

    if name == "software_middle_model_decide":
        decision = decide_with_middle_model(
            MiddleModelInput.from_dict(
                {
                    "task": str(_require(args, "task")),
                    "features": args.get("features") if isinstance(args.get("features"), dict) else {},
                    "candidates": args.get("candidates") if isinstance(args.get("candidates"), list) else [],
                    "confidence_threshold": args.get("confidence_threshold", 0.78),
                    "margin_threshold": args.get("margin_threshold", 0.12),
                    "rule_budget_ms": args.get("rule_budget_ms", 250),
                    "max_candidates": args.get("max_candidates", 8),
                    "model_hint": args.get("model_hint", "software-middle-small-model"),
                }
            )
        )
        return {"ok": True, "action": name, "decision": decision}

    if name == "enterprise_stack_plan":
        plan = build_enterprise_stack_plan(
            str(_require(args, "goal")),
            workspace,
            scale=str(args.get("scale", "") or ""),
            regulated=bool(args.get("regulated", False)),
            provider=str(args.get("provider", "main_deepseek") or "main_deepseek"),
        )
        return {"ok": True, "action": name, "plan": plan}

    if name == "distributed_platform_plan":
        plan = build_distributed_platform_plan()
        return {"ok": True, "action": name, "plan": plan}

    if name == "distributed_workload_catalog":
        return {"ok": True, "action": name, "workloads": list_distributed_workloads()}

    if name == "distributed_job_plan":
        plan = build_distributed_job_plan(
            job_id=str(_require(args, "job_id")),
            workload=str(_require(args, "workload")),
            entrypoint=str(args.get("entrypoint", "")),
            backend=str(args.get("backend", "ray_cluster")),
            source_manifest_id=str(args.get("source_manifest_id", "")),
            queue=str(args.get("queue", "default")),
            resources=args.get("resources") if isinstance(args.get("resources"), dict) else None,
        )
        return {"ok": True, "action": name, "plan": plan}

    if name == "project_model_program_plan":
        plan = build_project_model_program(
            ambition=str(args.get("ambition", "internet_scale") or "internet_scale"),
            target_context_tokens=int(args.get("target_context_tokens", 32768)),
        )
        return {"ok": bool(plan.get("validation", {}).get("ok")), "action": name, "plan": plan}

    if name == "project_holdout_benchmark_build":
        projectization_raw = Path(str(_require(args, "projectization_dir")))
        output_raw = Path(str(_require(args, "output_dir")))
        result = build_project_holdout_benchmark(
            ProjectHoldoutBenchmarkBuildInput(
                projectization_dir=projectization_raw if projectization_raw.is_absolute() else (workspace / projectization_raw),
                output_dir=output_raw if output_raw.is_absolute() else (workspace / output_raw),
            )
        )
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "project_holdout_evaluate":
        benchmark_raw = Path(str(_require(args, "benchmark_path")))
        predictions_raw = Path(str(_require(args, "predictions_path")))
        output_raw = Path(str(_require(args, "output_dir")))
        baseline_raw = _optional_path_arg(workspace, args, "baseline_report_path")
        report = evaluate_project_holdout(
            ProjectHoldoutEvaluationInput(
                benchmark_path=benchmark_raw if benchmark_raw.is_absolute() else (workspace / benchmark_raw),
                predictions_path=predictions_raw if predictions_raw.is_absolute() else (workspace / predictions_raw),
                output_dir=output_raw if output_raw.is_absolute() else (workspace / output_raw),
                baseline_report_path=baseline_raw,
            )
        )
        return {"ok": True, "action": name, "report": report}

    if name == "github_corpus_program_plan":
        return {"ok": True, "action": name, "plan": build_github_corpus_program()}

    if name == "github_corpus_status":
        output_root_raw = Path(str(_require(args, "output_root")))
        output_root = output_root_raw if output_root_raw.is_absolute() else (workspace / output_root_raw)
        status = build_corpus_flywheel_status(output_root)
        return {"ok": True, "action": name, "status": status}

    if name in {"github_corpus_scheduler_plan", "github_corpus_scheduler_cycle"}:
        output_root_raw = Path(str(_require(args, "output_root")))
        output_root = output_root_raw if output_root_raw.is_absolute() else (workspace / output_root_raw)
        scheduler_config = CorpusSchedulerConfig(
            output_root=output_root,
            seed_queries=_string_tuple_arg(args, "seed_queries"),
            local_repos=tuple(Path(x) for x in _string_tuple_arg(args, "local_repos")),
            web_results=tuple(dict(item) for item in args.get("web_results", []) if isinstance(item, dict))
            if isinstance(args.get("web_results"), list)
            else (),
            enable_github_network=bool(args.get("github", False)),
            interval_seconds=max(int(args.get("interval_seconds", 3600)), 1),
            repo_limit=max(int(args.get("repo_limit", 5)), 1),
            max_query_arms=max(int(args.get("max_query_arms", 4)), 1),
            min_stars=max(int(args.get("min_stars", 50)), 0),
            allowed_licenses=_string_tuple_arg(args, "allowed_licenses"),
            updated_after=str(args.get("updated_after", "")),
            quality_threshold=float(args.get("quality_threshold", 6.5)),
            downstream_metrics={
                str(key): float(value)
                for key, value in args.get("downstream_metrics", {}).items()
                if isinstance(value, (int, float))
            }
            if isinstance(args.get("downstream_metrics"), dict)
            else {},
            cpu_thread_budget=max(int(args.get("cpu_thread_budget", 2)), 1),
            max_cycles_retained=max(int(args.get("max_cycles_retained", 50)), 1),
        )
        if name == "github_corpus_scheduler_plan":
            plan = build_corpus_scheduler_plan(scheduler_config)
            return {"ok": bool(plan.get("validation", {}).get("ok")), "action": name, "plan": plan}
        cycle = run_corpus_scheduler_cycle(scheduler_config, force=bool(args.get("force", False)))
        return {"ok": bool(cycle.get("ran")) or cycle.get("status") == "skipped_cooldown", "action": name, "cycle": cycle}

    if name == "github_corpus_flywheel_cycle":
        output_root_raw = Path(str(_require(args, "output_root")))
        output_root = output_root_raw if output_root_raw.is_absolute() else (workspace / output_root_raw)
        downstream_metrics_path = _optional_path_arg(workspace, args, "downstream_metrics_path")
        predictions_path = _optional_path_arg(workspace, args, "predictions_path")
        baseline_report_path = _optional_path_arg(workspace, args, "baseline_report_path")
        result = run_corpus_flywheel_cycle(
            CorpusFlywheelInput(
                output_root=output_root,
                seed_queries=_string_tuple_arg(args, "seed_queries"),
                local_repos=tuple(Path(x) for x in _string_tuple_arg(args, "local_repos")),
                web_results=tuple(dict(item) for item in args.get("web_results", []) if isinstance(item, dict))
                if isinstance(args.get("web_results"), list)
                else (),
                enable_github_network=bool(args.get("github", False)),
                interval_seconds=max(int(args.get("interval_seconds", 3600)), 1),
                repo_limit=max(int(args.get("repo_limit", 5)), 1),
                max_query_arms=max(int(args.get("max_query_arms", 4)), 1),
                min_stars=max(int(args.get("min_stars", 50)), 0),
                allowed_licenses=_string_tuple_arg(args, "allowed_licenses"),
                updated_after=str(args.get("updated_after", "")),
                quality_threshold=float(args.get("quality_threshold", 6.5)),
                downstream_metrics={
                    str(key): float(value)
                    for key, value in args.get("downstream_metrics", {}).items()
                    if isinstance(value, (int, float))
                }
                if isinstance(args.get("downstream_metrics"), dict)
                else {},
                downstream_metrics_path=downstream_metrics_path,
                predictions_path=predictions_path,
                baseline_report_path=baseline_report_path,
                cpu_thread_budget=max(int(args.get("cpu_thread_budget", 2)), 1),
                max_cycles_retained=max(int(args.get("max_cycles_retained", 50)), 1),
                max_repos=max(int(args.get("max_repos", 50)), 0),
                max_files=max(int(args.get("max_files", 500)), 1),
                max_slices=max(int(args.get("max_slices", 800)), 1),
                max_symbol_examples_per_repo=max(int(args.get("max_symbol_examples_per_repo", 64)), 0),
                force=bool(args.get("force", False)),
            )
        )
        return {"ok": bool(result.get("ran")) or result.get("status") == "skipped_cooldown", "action": name, "flywheel": result}

    if name in {"github_corpus_projectization_plan", "github_corpus_projectize"}:
        crawl_output_raw = Path(str(_require(args, "crawl_output_dir")))
        output_dir_raw = Path(str(_require(args, "output_dir")))
        projectization_input = CorpusProjectizationInput(
            crawl_output_dir=crawl_output_raw if crawl_output_raw.is_absolute() else (workspace / crawl_output_raw),
            output_dir=output_dir_raw if output_dir_raw.is_absolute() else (workspace / output_dir_raw),
            allowed_routes=_string_tuple_arg(args, "allowed_routes") or ("train_now", "distill_pool", "benchmark_holdout"),
            max_repos=max(int(args.get("max_repos", 50)), 0),
            max_files=max(int(args.get("max_files", 500)), 1),
            max_slices=max(int(args.get("max_slices", 800)), 1),
            max_symbol_examples_per_repo=max(int(args.get("max_symbol_examples_per_repo", 64)), 0),
        )
        if name == "github_corpus_projectization_plan":
            plan = build_corpus_projectization_plan(projectization_input)
            return {"ok": True, "action": name, "plan": plan}
        result = materialize_corpus_projectization(projectization_input)
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "github_corpus_training_bundle":
        projectization_raw = Path(str(_require(args, "projectization_dir")))
        output_raw = Path(str(_require(args, "output_dir")))
        result = build_corpus_training_bundle(
            CorpusTrainingBundleInput(
                projectization_dir=projectization_raw if projectization_raw.is_absolute() else (workspace / projectization_raw),
                output_dir=output_raw if output_raw.is_absolute() else (workspace / output_raw),
                include_routes=_string_tuple_arg(args, "include_routes") or ("train_now", "distill_pool"),
                dataset_format=str(args.get("dataset_format", "messages") or "messages"),
                eval_ratio=float(args.get("eval_ratio", 0.15)),
                min_chars=int(args.get("min_chars", 20)),
                max_examples=int(args.get("max_examples", 2000)),
                model_hint=str(args.get("model_hint", "deepseek-coder") or "deepseek-coder"),
                include_protocol_examples=bool(args.get("include_protocol_examples", True)),
                protocol_example_limit=int(args.get("protocol_example_limit", 0)),
                prepare_dataset=bool(args.get("prepare_dataset", False)),
            )
        )
        return {"ok": bool(result.manifest.get("validation", {}).get("ok")), "action": name, **result.to_dict()}

    if name == "github_query_plan_build":
        plan = build_github_query_plan(
            seed_queries=[str(item) for item in args.get("seed_queries", []) if str(item).strip()],
            web_results=args.get("web_results") if isinstance(args.get("web_results"), list) else [],
            strategy=args.get("strategy") if isinstance(args.get("strategy"), dict) else {},
            max_queries=int(args.get("max_queries", 12)),
        )
        return {"ok": True, "action": name, "plan": plan}

    if name == "github_candidate_rank":
        ranking = rank_repo_profiles(
            query=str(args.get("query", "") or ""),
            profiles=args.get("profiles") if isinstance(args.get("profiles"), list) else [],
            web_results=args.get("web_results") if isinstance(args.get("web_results"), list) else [],
            feedback_by_tag=args.get("feedback_by_tag") if isinstance(args.get("feedback_by_tag"), dict) else {},
            strategy=args.get("strategy") if isinstance(args.get("strategy"), dict) else {},
            allowed_licenses={
                str(item).lower()
                for item in args.get("allowed_licenses", [])
                if str(item).strip()
            }
            if isinstance(args.get("allowed_licenses"), list)
            else set(),
            min_quality=float(args.get("min_quality", 6.5)),
        )
        return {"ok": True, "action": name, "ranking": ranking}

    if name == "corpus_feedback_plan":
        feedback = build_corpus_feedback_report(
            ranking=args.get("ranking") if isinstance(args.get("ranking"), dict) else {},
            downstream_metrics=args.get("downstream_metrics") if isinstance(args.get("downstream_metrics"), dict) else {},
            target_train_now_rate=float(args.get("target_train_now_rate", 0.35)),
        )
        return {"ok": True, "action": name, "feedback": feedback}

    if name == "project_repo_memory_build":
        repo_path_raw = Path(str(_require(args, "repo_path")))
        output_dir_raw = Path(str(_require(args, "output_dir")))
        repo_path = repo_path_raw if repo_path_raw.is_absolute() else (workspace / repo_path_raw)
        output_dir = output_dir_raw if output_dir_raw.is_absolute() else (workspace / output_dir_raw)
        result = build_repo_memory(
            RepoMemoryBuildInput(
                repo_path=repo_path,
                output_dir=output_dir,
                max_files=int(args.get("max_files", 500)),
                max_slices=int(args.get("max_slices", 800)),
            )
        )
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "project_task_synthesis_build":
        output_dir_raw = Path(str(_require(args, "output_dir")))
        output_dir = output_dir_raw if output_dir_raw.is_absolute() else (workspace / output_dir_raw)
        memory_dirs = tuple(
            path if path.is_absolute() else (workspace / path)
            for path in _path_tuple_arg(args, "memory_dirs")
        )
        result = synthesize_project_tasks(
            ProjectTaskSynthesisInput(
                memory_dirs=memory_dirs,
                output_dir=output_dir,
                max_symbol_examples_per_repo=int(args.get("max_symbol_examples_per_repo", 64)),
            )
        )
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "training_platform_blueprint":
        blueprint = build_training_platform_blueprint()
        return {"ok": True, "action": name, "blueprint": blueprint}

    if name == "training_recipe_plan":
        recipe = build_training_recipe(
            name=str(_require(args, "name")),
            research_question=str(_require(args, "research_question")),
            base_model=str(_require(args, "base_model")),
            objective=str(_require(args, "objective")),
            task_mix=args.get("task_mix") if isinstance(args.get("task_mix"), dict) else {},
            data_mix=args.get("data_mix") if isinstance(args.get("data_mix"), dict) else {},
            teacher_mix=args.get("teacher_mix") if isinstance(args.get("teacher_mix"), dict) else {},
            method=args.get("method") if isinstance(args.get("method"), dict) else {},
            evaluation_suite=_string_tuple_arg(args, "evaluation_suite"),
            knobs=args.get("knobs") if isinstance(args.get("knobs"), dict) else {},
            notes=str(args.get("notes", "") or ""),
        )
        return {"ok": bool(recipe.get("validation", {}).get("ok")), "action": name, "recipe": recipe}

    if name == "ablation_plan_build":
        plan = build_ablation_plan(
            name=str(_require(args, "name")),
            research_question=str(_require(args, "research_question")),
            baseline_recipe=dict(_require(args, "baseline_recipe")),
            variants=[dict(item) for item in args.get("variants", []) if isinstance(item, dict)],
            primary_metrics=_string_tuple_arg(args, "primary_metrics"),
            success_criteria=_string_tuple_arg(args, "success_criteria"),
        )
        return {"ok": bool(plan.get("validation", {}).get("ok")), "action": name, "plan": plan}

    if name == "teacher_registry":
        return {
            "ok": True,
            "action": name,
            "teachers": list_teacher_models(),
            "tasks": list_teacher_tasks(),
        }

    if name == "teacher_task_suite_plan":
        suite = build_teacher_task_suite(
            name=str(_require(args, "name")),
            task_mix=args.get("task_mix") if isinstance(args.get("task_mix"), dict) else None,
            evidence_policy=str(args.get("evidence_policy", "required") or "required"),
        )
        return {"ok": bool(suite.get("validation", {}).get("ok")), "action": name, "suite": suite}

    if name == "distillation_plan_build":
        plan = build_distillation_plan(
            name=str(_require(args, "name")),
            student_model=str(_require(args, "student_model")),
            teacher_mix=args.get("teacher_mix") if isinstance(args.get("teacher_mix"), dict) else {},
            task_suite=dict(_require(args, "task_suite")),
            target_recipe_id=str(args.get("target_recipe_id", "") or ""),
            consensus_policy=str(args.get("consensus_policy", "single_teacher") or "single_teacher"),
            output_policy=str(args.get("output_policy", "concise_grounded_answer") or "concise_grounded_answer"),
            acceptance_thresholds=(
                args.get("acceptance_thresholds")
                if isinstance(args.get("acceptance_thresholds"), dict)
                else None
            ),
        )
        return {"ok": bool(plan.get("validation", {}).get("ok")), "action": name, "plan": plan}

    if name == "distillation_dataset_manifest_build":
        manifest = build_distillation_dataset_manifest(
            distillation_plan=dict(_require(args, "distillation_plan")),
            teacher_outputs=[dict(item) for item in args.get("teacher_outputs", []) if isinstance(item, dict)],
        )
        return {"ok": bool(manifest.get("validation", {}).get("ok")), "action": name, "manifest": manifest}

    if name == "teacher_prompt_batch_build":
        batch = build_teacher_prompt_batch(
            distillation_plan=dict(_require(args, "distillation_plan")),
            source_examples=[dict(item) for item in args.get("source_examples", []) if isinstance(item, dict)],
            max_prompts=int(args.get("max_prompts", 0)),
        )
        return {"ok": bool(batch.get("validation", {}).get("ok")), "action": name, "batch": batch}

    if name == "teacher_execution_plan_build":
        plan = build_teacher_execution_plan(
            distillation_plan=dict(_require(args, "distillation_plan")),
            prompt_batch=dict(_require(args, "prompt_batch")),
            mode=str(args.get("mode", "dry_run") or "dry_run"),
            allow_remote=bool(args.get("allow_remote", False)),
            max_prompts=int(args.get("max_prompts", 0)),
            max_output_tokens=int(args.get("max_output_tokens", 1024)),
            temperature=float(args.get("temperature", 0.0)),
        )
        return {"ok": bool(plan.get("validation", {}).get("ok")), "action": name, "plan": plan}

    if name == "teacher_execution_run":
        result = run_teacher_execution(
            execution_plan=dict(_require(args, "execution_plan")),
            timeout=float(args.get("timeout", 90.0)),
            max_retries=int(args.get("max_retries", 1)),
        )
        return {"ok": bool(result.get("validation", {}).get("ok")), "action": name, "result": result}

    if name == "teacher_output_review_build":
        review = review_teacher_outputs(
            distillation_plan=dict(_require(args, "distillation_plan")),
            prompt_batch=dict(_require(args, "prompt_batch")),
            teacher_outputs=[dict(item) for item in args.get("teacher_outputs", []) if isinstance(item, dict)],
        )
        return {"ok": bool(review.get("validation", {}).get("ok")), "action": name, "review": review}

    if name == "distillation_export_build":
        output_dir_raw = Path(str(_require(args, "output_dir")))
        output_dir = output_dir_raw if output_dir_raw.is_absolute() else (workspace / output_dir_raw)
        result = export_distillation_training_examples(
            output_dir=output_dir,
            distillation_plan=dict(_require(args, "distillation_plan")),
            teacher_output_review=dict(_require(args, "teacher_output_review")),
        )
        return {
            "ok": bool(result.get("counts", {}).get("training_examples", 0)),
            "action": name,
            **result,
        }

    if name == "first_training_round_plan":
        plan = build_first_training_round_plan(
            name=str(_require(args, "name")),
            learning_dirs=_string_tuple_arg(args, "learning_dirs"),
            solution_dirs=_string_tuple_arg(args, "solution_dirs"),
            training_output_dir=str(_require(args, "training_output_dir")),
            model_output_dir=str(_require(args, "model_output_dir")),
            base_model=str(args.get("base_model", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B") or ""),
            dataset_format=str(args.get("dataset_format", "messages") or "messages"),
            eval_ratio=float(args.get("eval_ratio", 0.15)),
            min_chars=int(args.get("min_chars", 20)),
            max_examples=int(args.get("max_examples", 2000)),
            include_protocol_examples=bool(args.get("include_protocol_examples", True)),
            protocol_example_limit=int(args.get("protocol_example_limit", 0)),
            min_train_examples=int(args.get("min_train_examples", 20)),
            notes=str(args.get("notes", "") or ""),
        )
        return {"ok": bool(plan.get("validation", {}).get("ok")), "action": name, "plan": plan}

    if name == "training_server_preflight":
        policy = args.get("policy") if isinstance(args.get("policy"), dict) else build_training_resource_policy()
        preflight = run_server_resource_preflight(policy=policy)
        return {
            "ok": bool(preflight.get("admission", {}).get("admitted")),
            "action": name,
            "preflight": preflight,
        }

    if name == "industrial_maturity_plan":
        plan = build_industrial_maturity_plan(
            str(_require(args, "goal")),
            workspace,
            scale=str(args.get("scale", "listed") or "listed"),
            regulated=bool(args.get("regulated", True)),
            provider=str(args.get("provider", "main_deepseek") or "main_deepseek"),
        )
        return {"ok": True, "action": name, "plan": plan}

    if name == "enterprise_readiness_check":
        report = build_enterprise_readiness_report(workspace)
        return {"ok": not bool(report.get("summary", {}).get("release_blocked")), "action": name, "report": report}

    if name == "workflow_validate":
        result = validate_workflow_spec(args.get("spec") or {})
        return {"ok": bool(result.get("ok")), "action": name, "validation": result}

    if name == "innovation_radar":
        radar = build_innovation_radar(workspace, roots=_path_tuple_arg(args, "roots"))
        return {"ok": True, "action": name, "radar": radar}

    if name == "intent_compile":
        compilation = compile_intent(str(_require(args, "goal")), workspace, roots=_path_tuple_arg(args, "roots"))
        return {"ok": bool(compilation.get("validation", {}).get("ok")), "action": name, "compilation": compilation}

    if name == "workflow_dry_run":
        dry_run = dry_run_workflow(args.get("spec") or {}, workspace)
        return {"ok": bool(dry_run.get("ok")), "action": name, "dry_run": dry_run}

    if name == "evidence_ledger":
        ledger = build_evidence_ledger(
            workspace,
            roots=_path_tuple_arg(args, "roots"),
            write_path=_optional_path_arg(workspace, args, "output_path"),
        )
        return {"ok": True, "action": name, "ledger": ledger}

    if name == "research_feedback_report":
        raw_roots = _path_tuple_arg(args, "roots")
        roots = tuple(path if path.is_absolute() else (workspace / path) for path in raw_roots) or (workspace,)
        report = build_research_feedback_report(
            roots,
            low_score_threshold=float(args.get("low_score_threshold", 6.5)),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "action": name, "report": report, "output_path": str(output_path) if output_path else ""}

    if name == "solution_publish":
        result = publish_solution_from_run(
            workspace,
            output_dir=_optional_path_arg(workspace, args, "output_dir"),
            title=str(args.get("title", "") or ""),
            source_type=str(args.get("source_type", "product_run") or "product_run"),
        )
        return {"action": name, **result}

    if name == "research_synthesize":
        query = str(_require(args, "query"))
        top_k = int(args.get("top_k", 4))
        result = run_research_chain(
            ResearchChainInput(
                query=query,
                workspace=workspace,
                solution_dirs=_path_tuple_arg(args, "solution_dirs"),
                learning_dirs=_string_tuple_arg(args, "learning_dirs"),
                top_k=max(top_k, 1),
                use_web=bool(args.get("use_web", False)),
                web_provider=str(args.get("web_provider", "duckduckgo")),
                use_llm=bool(args.get("use_llm", False)),
                llm_provider=str(args.get("llm_provider", "openai")),
                llm_model=str(args.get("llm_model")).strip() if args.get("llm_model") else None,
                use_cache=bool(args.get("use_cache", True)),
                refresh_cache=bool(args.get("refresh_cache", False)),
                cache_ttl_seconds=int(args.get("cache_ttl_seconds", 86400)),
            )
        )
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "training_prepare":
        output_dir = Path(str(_require(args, "output_dir")))
        result = prepare_fine_tuning_dataset(
            TrainingPrepareInput(
                output_dir=output_dir,
                learning_dirs=tuple(Path(x) for x in _string_tuple_arg(args, "learning_dirs")),
                solution_dirs=_path_tuple_arg(args, "solution_dirs"),
                dataset_format=str(args.get("dataset_format", "messages")),
                eval_ratio=float(args.get("eval_ratio", 0.15)),
                min_chars=int(args.get("min_chars", 20)),
                max_examples=int(args.get("max_examples", 2000)),
                model_hint=str(args.get("model_hint", "deepseek")),
                include_protocol_examples=bool(args.get("include_protocol_examples", True)),
                protocol_example_limit=int(args.get("protocol_example_limit", 0)),
            )
        )
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "backup_model_train":
        result = prepare_backup_model_training(
            BackupModelTrainInput(
                training_dir=Path(str(_require(args, "training_dir"))),
                output_dir=Path(str(_require(args, "output_dir"))),
                base_model=str(args.get("base_model", "") or ""),
                adapter_name=str(args.get("adapter_name", "backup-local-lora") or "backup-local-lora"),
                trainer_backend=str(args.get("trainer_backend", "trl_sft") or "trl_sft"),
                launch=bool(args.get("launch", False)),
                min_quality_score=float(args.get("min_quality_score", 6.5)),
                min_train_examples=int(args.get("min_train_examples", 20)),
                max_seq_length=int(args.get("max_seq_length", 2048)),
                learning_rate=float(args.get("learning_rate", 2e-4)),
                epochs=float(args.get("epochs", 1.0)),
            )
        )
        return {"ok": bool(result.launchable or result.status.startswith("prepared")), "action": name, **result.to_dict()}

    if name == "github_crawl_profile":
        output_dir = Path(str(_require(args, "output_dir")))
        result = crawl_frontend_backend_repos(
            CrawlProfileInput(
                query=str(args.get("query", "")),
                output_dir=output_dir,
                local_repos=tuple(Path(x) for x in _string_tuple_arg(args, "local_repos")),
                seed_queries=_string_tuple_arg(args, "seed_queries"),
                web_results=tuple(
                    dict(item)
                    for item in args.get("web_results", [])
                    if isinstance(item, dict)
                )
                if isinstance(args.get("web_results"), list)
                else (),
                enable_github_network=bool(args.get("github", False)),
                repo_limit=max(int(args.get("repo_limit", 5)), 1),
                max_query_arms=max(int(args.get("max_query_arms", 4)), 1),
                min_stars=max(int(args.get("min_stars", 50)), 0),
                allowed_licenses=_string_tuple_arg(args, "allowed_licenses"),
                updated_after=str(args.get("updated_after", "")),
                quality_threshold=float(args.get("quality_threshold", 6.5)),
                downstream_metrics={
                    str(key): float(value)
                    for key, value in args.get("downstream_metrics", {}).items()
                    if isinstance(value, (int, float))
                }
                if isinstance(args.get("downstream_metrics"), dict)
                else {},
                prior_strategy=args.get("strategy") if isinstance(args.get("strategy"), dict) else {},
            )
        )
        return {"ok": True, "action": name, **result.to_dict()}

    if name == "finish":
        reason = str(args.get("reason", "done"))
        return {"ok": True, "action": name, "finished": True, "reason": reason}
    # 未知动作处理
    raise ExecutorError(f"unknown action: {name}")


def run(workspace: Path, action_json_line: str, limits: ExecutionLimits | None = None) -> dict[str, Any]:
    obj = parse_action(action_json_line)
    return run_action(workspace, obj, limits=limits)
