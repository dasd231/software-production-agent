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
from agent.cloud_native import build_cloud_native_deep_dive_plan
from agent.command_api import build_command_api_plan
from agent.context_pv import ContextPVPolicy, manifest_to_jsonl as context_pv_manifest_to_jsonl, plan_context_pv, render_context_pv_bundle
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
from agent.evaluation.automation_scorecard import build_automation_scorecard, evaluate_scorecard_evidence
from agent.graph_runtime import (
    build_graph_runtime_plan,
    graph_rag_query,
    load_agent_events_graph,
    render_cypher_import_bundle,
    review_policy_versions,
)
from agent.innovation.radar import build_innovation_radar
from agent.intent.compiler import compile_intent
from agent.integrations.embedding import build_integration_embed_plan, list_integration_catalog
from agent.local_training import run_local_training
from agent.llm.runtime import model_runtime_status
from agent.learning.web_search import search_web
from agent.mcp.adapter import default_mcp_capabilities, invoke_mcp_tool
from agent.operations import build_operations_readiness_plan
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
from agent.software_middle_model import (
    MiddleModelInput,
    MiddleModelDatasetExportInput,
    MiddleModelServerHandoffInput,
    append_middle_model_trace,
    build_middle_model_trace,
    build_software_middle_model_plan,
    decide_with_middle_model,
    export_middle_model_trace_dataset,
    prepare_middle_model_server_handoff,
)
from agent.training.studio import (
    build_ablation_plan,
    build_training_platform_blueprint,
    build_training_recipe,
)
from agent.training.rounds import build_first_training_round_plan
from agent.training.resource_guard import build_training_resource_policy, run_server_resource_preflight
from agent.resources.registry import discover_resources
from agent.resilience import build_resilience_plan
from agent.rule_compiler import compile_business_rules
from agent.runtime.production_check import run_production_checks
from agent.scheduler.admission import get_global_admission_controller
from agent.scheduler.routing import build_model_route_plan
from agent.skill_runtime import build_skill_runtime_plan
from agent.sandbox.k8s_job import K8sSandboxResources, K8sSandboxSpec, manifest_to_jsonl, render_sandbox_bundle
from agent.solution_library.publish import publish_solution_from_run
from agent.supervisor.policy import review_action
from agent.evaluation.feedback import build_research_feedback_report
from agent.tools import file_tools
from agent.tools import git_tools
from agent.tools.workspace_index import build_workspace_index
from agent.tools.shell_tools import run_shell
from agent.workflow import compile_enterprise_workflow, query_enterprise_workflow_contract
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


def _supervisor_error_code(status: str) -> str:
    if status == "human_required":
        return "SUPERVISOR_HUMAN_REQUIRED"
    if status == "sandbox_required":
        return "SUPERVISOR_SANDBOX_REQUIRED"
    return "SUPERVISOR_DENIED"


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
        supervision = review_action(
            action_name,
            args,
            workspace=workspace,
            granted_permissions=lim.granted_permissions,
            confirmed_actions=lim.confirmed_actions,
        )
        preflight["supervisor"] = supervision.to_dict()
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
        if not supervision.allowed:
            code = _supervisor_error_code(supervision.status)
            return _error_envelope(
                action=action_name,
                error_code=code,
                error=supervision.reason,
                retryable=False,
                recommended_action=supervision.recommended_action,
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
        middle_input = MiddleModelInput.from_dict(
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
        decision = decide_with_middle_model(middle_input)
        trace_path = _optional_path_arg(workspace, args, "trace_output_path")
        trace_write: dict[str, Any] | None = None
        if trace_path is not None:
            trace = build_middle_model_trace(
                middle_input,
                decision,
                final_accepted=args.get("final_accepted") if isinstance(args.get("final_accepted"), bool) else None,
                latency_saved_ms=args.get("latency_saved_ms"),
                quality_delta=args.get("quality_delta"),
                source_trace_id=str(args.get("source_trace_id", "") or ""),
                outcome=args.get("outcome") if isinstance(args.get("outcome"), dict) else {},
            )
            trace_write = append_middle_model_trace(trace_path, trace)
        result = {"ok": True, "action": name, "decision": decision}
        if trace_write is not None:
            result["trace"] = trace_write
        return result

    if name == "software_middle_model_dataset_export":
        output_raw = Path(str(_require(args, "output_dir")))
        result = export_middle_model_trace_dataset(
            MiddleModelDatasetExportInput(
                trace_paths=tuple(
                    (Path(item) if Path(item).is_absolute() else workspace / Path(item))
                    for item in _string_tuple_arg(args, "trace_paths")
                ),
                output_dir=output_raw if output_raw.is_absolute() else workspace / output_raw,
                base_model=str(args.get("base_model", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B") or ""),
                dataset_format=str(args.get("dataset_format", "messages") or "messages"),
                eval_ratio=float(args.get("eval_ratio", 0.15)),
                min_traces=int(args.get("min_traces", 1)),
                max_examples=int(args.get("max_examples", 2000)),
                notes=str(args.get("notes", "") or ""),
            )
        )
        return {"ok": bool(result.validation.get("ok")), "action": name, **result.to_dict()}

    if name == "software_middle_model_server_handoff":
        training_raw = Path(str(_require(args, "training_dir")))
        output_raw = Path(str(_require(args, "output_dir")))
        result = prepare_middle_model_server_handoff(
            MiddleModelServerHandoffInput(
                training_dir=training_raw if training_raw.is_absolute() else workspace / training_raw,
                output_dir=output_raw if output_raw.is_absolute() else workspace / output_raw,
                base_model=str(args.get("base_model", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B") or ""),
                adapter_name=str(args.get("adapter_name", "software-middle-model-lora") or "software-middle-model-lora"),
                min_train_examples=int(args.get("min_train_examples", 1)),
                max_seq_length=int(args.get("max_seq_length", 1024)),
                learning_rate=float(args.get("learning_rate", 2e-4)),
                epochs=float(args.get("epochs", 1.0)),
                cpu_threads=int(args.get("cpu_threads", 4)),
                max_gpu_memory_gb=float(args.get("max_gpu_memory_gb", 12.0)),
            )
        )
        return {"ok": bool(result.handoff_ready), "action": name, **result.to_dict()}

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

    if name == "k8s_sandbox_plan":
        command = str(_require(args, "command"))
        resources = K8sSandboxResources(
            cpu_request=str(args.get("cpu_request", "100m") or "100m"),
            cpu_limit=str(args.get("cpu_limit", "500m") or "500m"),
            memory_request=str(args.get("memory_request", "128Mi") or "128Mi"),
            memory_limit=str(args.get("memory_limit", "512Mi") or "512Mi"),
        )
        sandbox_spec = K8sSandboxSpec(
            namespace=str(args.get("namespace", "agent-sandbox") or "agent-sandbox"),
            image=str(args.get("image", "python:3.12-slim") or "python:3.12-slim"),
            network=str(args.get("network", "none") or "none"),
            active_deadline_seconds=int(args.get("active_deadline_seconds", 300) or 300),
            ttl_seconds_after_finished=int(args.get("ttl_seconds_after_finished", 600) or 600),
            resources=resources,
        )
        action_for_job = {"type": "action", "action": "run_command", "args": {"command": command}}
        manifest_docs = render_sandbox_bundle(action_for_job, spec=sandbox_spec)
        manifest_text = manifest_to_jsonl(manifest_docs)
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("k8s_sandbox_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(manifest_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(manifest_text.encode("utf-8"))}
        result: dict[str, Any] = {
            "ok": True,
            "action": name,
            "sandbox": sandbox_spec.to_dict(),
            "manifest": manifest_docs,
            "manifest_text": manifest_text,
            "doc_count": len(manifest_docs),
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "context_pv_plan":
        text = str(_require(args, "text"))
        policy = ContextPVPolicy(
            tenant=str(args.get("tenant", "default") or "default"),
            namespace=str(args.get("namespace", "context-pv") or "context-pv"),
            single_pv_token_threshold=int(args.get("single_pv_token_threshold", 4096) or 4096),
            target_slice_tokens=int(args.get("target_slice_tokens", 2048) or 2048),
            max_slice_tokens=int(args.get("max_slice_tokens", 3072) or 3072),
            overlap_tokens=int(args.get("overlap_tokens", 256) or 256),
            hot_tier_token_budget=int(args.get("hot_tier_token_budget", 8192) or 8192),
            warm_tier_token_budget=int(args.get("warm_tier_token_budget", 32768) or 32768),
            route_top_k=int(args.get("route_top_k", 6) or 6),
            replica_factor_critical=int(args.get("replica_factor_critical", 2) or 2),
        ).normalized()
        plan = plan_context_pv(
            text,
            query=str(args.get("query", "") or ""),
            policy=policy,
            version=str(args.get("version", "v1") or "v1"),
        )
        include_text = bool(args.get("include_text", False))
        plan_dict = plan.to_dict(include_text=include_text)
        k8s_docs: list[dict[str, Any]] = []
        if bool(args.get("render_k8s", True)):
            k8s_docs = render_context_pv_bundle(plan)
            plan_dict["k8s"] = {
                "doc_count": len(k8s_docs),
                "kinds": [str(doc.get("kind", "")) for doc in k8s_docs],
                "manifest_text": context_pv_manifest_to_jsonl(k8s_docs),
            }
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("context_pv_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan_dict, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        result: dict[str, Any] = {
            "ok": True,
            "action": name,
            "plan": plan_dict,
            "summary": {
                "manifest_id": plan.manifest.manifest_id,
                "total_tokens": plan.manifest.total_tokens,
                "slice_count": len(plan.manifest.slices),
                "placement_count": len(plan.manifest.placements),
                "merkle_root": plan.manifest.merkle_root,
                "routed_slice_ids": list(plan.load_plan.get("required_slice_ids", [])),
                "k8s_doc_count": len(k8s_docs),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "resilience_plan":
        plan = build_resilience_plan(
            surface=str(args.get("surface", "software-production-agent") or "software-production-agent"),
            payment_enabled=bool(args.get("payment_enabled", True)),
            payment_provider=str(args.get("payment_provider", "generic") or "generic"),
            threat_level=str(args.get("threat_level", "internet") or "internet"),
        )
        plan_dict = plan.to_dict()
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("resilience_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan_dict, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        result: dict[str, Any] = {
            "ok": True,
            "action": name,
            "plan": plan_dict,
            "summary": {
                "surface": plan.surface,
                "threat_level": plan.threat_level,
                "payment_enabled": bool(plan.payment.get("enabled")),
                "chaos_drill_count": len(plan.chaos_drills),
                "attack_layer_count": len(plan.attack_resistance.get("layers", [])),
                "rate_limit_count": len(plan.anti_crawl.get("rate_limits", [])),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "business_rule_compile":
        compilation = compile_business_rules(
            str(_require(args, "rules")),
            domain_hint=str(args.get("domain_hint", "") or ""),
        )
        compiled = compilation.to_dict()
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("business_rule_compile output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(compiled, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        result: dict[str, Any] = {
            "ok": compilation.ok,
            "action": name,
            "compilation": compiled,
            "summary": {
                "domain": compilation.domain,
                "entity_count": len(compilation.entities),
                "state_count": len(compilation.states),
                "transition_count": len(compilation.transitions),
                "api_count": len(compilation.api_contracts),
                "finding_count": len(compilation.findings),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "automation_scorecard_plan":
        scorecard = build_automation_scorecard(
            demand_count=int(args.get("demand_count", 10) or 10),
            observation_days=int(args.get("observation_days", 30) or 30),
            include_agent_failures=bool(args.get("include_agent_failures", True)),
            third_party_review=bool(args.get("third_party_review", True)),
        )
        evidence = args.get("evidence") if isinstance(args.get("evidence"), dict) else {}
        review = evaluate_scorecard_evidence(evidence) if evidence else {"schema": "automation_scorecard_evidence_review.v1", "ok": True, "findings": []}
        payload = {"scorecard": scorecard, "evidence_review": review}
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("automation_scorecard_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(payload, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        result: dict[str, Any] = {
            "ok": bool(review.get("ok", True)),
            "action": name,
            **payload,
            "summary": {
                "metric_count": len(scorecard.get("metrics", [])),
                "anti_cheat_count": len(scorecard.get("anti_cheat_rules", [])),
                "evidence_findings": len(review.get("findings", [])),
                "experiment_demands": scorecard.get("experiment", {}).get("minimum_real_demands"),
                "observation_days": scorecard.get("experiment", {}).get("observation_days"),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "graph_runtime_plan":
        plan = build_graph_runtime_plan(
            str(args.get("goal", "软件生产 Agent 图运行时二改") or "软件生产 Agent 图运行时二改"),
            include_cypher=bool(args.get("include_cypher", True)),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("graph_runtime_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        summary = {
            "modification_count": len(plan.get("langgraph_second_modifications", [])),
            "runtime_node_count": len(plan.get("runtime_graph", {}).get("nodes", [])),
            "runtime_edge_count": len(plan.get("runtime_graph", {}).get("edges", [])),
            "graph_label_count": len(plan.get("graph_db_schema", {}).get("node_labels", [])),
            "graph_query_count": len(plan.get("graph_query_catalog", [])),
        }
        result: dict[str, Any] = {"ok": True, "action": name, "plan": plan, "summary": summary}
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "graph_events_ingest":
        events_path = _optional_path_arg(workspace, args, "events_path")
        if events_path is None:
            raise ExecutorError("graph_events_ingest requires events_path")
        try:
            events_path.relative_to(workspace.resolve())
        except ValueError as exc:
            raise ExecutorError("graph_events_ingest events_path must stay inside workspace") from exc
        if not events_path.exists():
            raise ExecutorError(f"graph_events_ingest events_path not found: {events_path}")
        graph, ingest_summary = load_agent_events_graph(events_path)
        query = str(args.get("query", "") or "")
        rag_result = (
            graph_rag_query(
                graph,
                query,
                top_k=int(args.get("top_k", 5) or 5),
                neighbor_budget=int(args.get("neighbor_budget", 12) or 12),
            )
            if query.strip()
            else {}
        )
        payload = {
            "schema": "graph_events_ingest_result.v1",
            "summary": ingest_summary,
            "graph": graph.to_dict(),
            "graph_rag": rag_result,
            "policy_review": review_policy_versions(graph),
            "cypher_seed": graph.to_cypher_seed() if bool(args.get("include_cypher", True)) else "",
            "graph_store_import": render_cypher_import_bundle(graph, dialect="neo4j"),
        }
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("graph_events_ingest output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(payload, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        summary = {
            **ingest_summary,
            "graph_rag_anchor_count": len(rag_result.get("anchor_nodes", [])) if isinstance(rag_result, dict) else 0,
            "cypher_included": bool(payload.get("cypher_seed")),
        }
        result: dict[str, Any] = {"ok": True, "action": name, **payload, "summary": summary}
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "operations_readiness_plan":
        plan = build_operations_readiness_plan(
            service_name=str(args.get("service_name", "software-production-agent") or "software-production-agent"),
            replicas=int(args.get("replicas", 3) or 3),
            slo_target=float(args.get("slo_target", 0.995) or 0.995),
            checks=args.get("checks") if isinstance(args.get("checks"), list) else None,
            agents=args.get("agents") if isinstance(args.get("agents"), list) else None,
            tasks=args.get("tasks") if isinstance(args.get("tasks"), list) else None,
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("operations_readiness_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        health_snapshot = plan.get("health", {}).get("snapshot", {})
        failover_summary = plan.get("multi_agent", {}).get("failover_decision", {}).get("summary", {})
        result = {
            "ok": str(health_snapshot.get("status")) != "unhealthy",
            "action": name,
            "plan": plan,
            "summary": {
                "health_status": health_snapshot.get("status"),
                "ready": bool(health_snapshot.get("ready", False)),
                "monitoring_metric_count": len(plan.get("monitoring", {}).get("agent_specific_metrics", [])),
                "alert_count": len(plan.get("monitoring", {}).get("alerts", [])),
                "healthy_agent_count": failover_summary.get("healthy_count", 0),
                "reassignment_count": failover_summary.get("reassignment_count", 0),
                "dead_letter_count": failover_summary.get("dead_letter_count", 0),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "cloud_native_deep_dive_plan":
        plan = build_cloud_native_deep_dive_plan(
            focus=str(args.get("focus", "agent-platform") or "agent-platform"),
            kubernetes_version=str(args.get("kubernetes_version", "v1.36") or "v1.36"),
            include_sources=bool(args.get("include_sources", True)),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("cloud_native_deep_dive_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        k8s = plan.get("kubernetes_resource_scheduling", {})
        storage = k8s.get("storage_control_plane", {}) if isinstance(k8s, dict) else {}
        result = {
            "ok": True,
            "action": name,
            "plan": plan,
            "summary": {
                "focus": plan.get("focus"),
                "source_count": len(plan.get("sources", [])) if isinstance(plan.get("sources"), list) else 0,
                "collapse_route_count": len(
                    plan.get("multi_agent_similarity_collapse", {}).get("route", [])
                )
                if isinstance(plan.get("multi_agent_similarity_collapse"), dict)
                else 0,
                "etcd_algorithm_count": len(plan.get("etcd_memory_optimization", {}).get("algorithms", []))
                if isinstance(plan.get("etcd_memory_optimization"), dict)
                else 0,
                "scheduler_extension_count": len(k8s.get("scheduler_framework", {}).get("cycle", []))
                if isinstance(k8s, dict)
                else 0,
                "storage_controller_count": len(storage.get("pv_controller", {}).get("workers", []))
                if isinstance(storage, dict)
                else 0,
                "prometheus_metric_count": len(plan.get("prometheus_scorecard", {}).get("metrics", []))
                if isinstance(plan.get("prometheus_scorecard"), dict)
                else 0,
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "enterprise_workflow_compile":
        contract = compile_enterprise_workflow(
            args.get("spec") if isinstance(args.get("spec"), dict) else None,
            goal=str(args.get("goal", "企业级多智能体工作流") or "企业级多智能体工作流"),
            domain=str(args.get("domain", "bio_research") or "bio_research"),
            include_delivery_plan=bool(args.get("include_delivery_plan", True)),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("enterprise_workflow_compile output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(contract, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        assessment = contract.get("assessment", {}) if isinstance(contract.get("assessment"), dict) else {}
        risk_counts = assessment.get("risk_counts", {}) if isinstance(assessment.get("risk_counts"), dict) else {}
        result = {
            "ok": bool(contract.get("ok")) and str(assessment.get("readiness")) != "blocked",
            "action": name,
            "contract": contract,
            "summary": {
                "workflow_name": contract.get("workflow", {}).get("name")
                if isinstance(contract.get("workflow"), dict)
                else "",
                "node_count": len(contract.get("nodes", [])) if isinstance(contract.get("nodes"), list) else 0,
                "edge_count": len(contract.get("edges", [])) if isinstance(contract.get("edges"), list) else 0,
                "score": assessment.get("score"),
                "readiness": assessment.get("readiness"),
                "finding_count": assessment.get("finding_count"),
                "high_risk_count": int(risk_counts.get("high", 0) or 0) + int(risk_counts.get("critical", 0) or 0),
                "delivery_stage_count": len(contract.get("enterprise_delivery_plan", []))
                if isinstance(contract.get("enterprise_delivery_plan"), list)
                else 0,
                "graph_node_count": len(contract.get("graph_projection", {}).get("nodes", []))
                if isinstance(contract.get("graph_projection"), dict)
                else 0,
                "graph_edge_count": len(contract.get("graph_projection", {}).get("edges", []))
                if isinstance(contract.get("graph_projection"), dict)
                else 0,
                "cypher_bytes": len(str(contract.get("cypher_seed", "")).encode("utf-8")),
                "mermaid_bytes": len(str(contract.get("mermaid", "")).encode("utf-8")),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "enterprise_workflow_query":
        contract = compile_enterprise_workflow(
            args.get("spec") if isinstance(args.get("spec"), dict) else None,
            goal=str(args.get("goal", "企业级多智能体工作流") or "企业级多智能体工作流"),
            domain=str(args.get("domain", "bio_research") or "bio_research"),
            include_delivery_plan=True,
        )
        query_result = query_enterprise_workflow_contract(
            contract,
            str(args.get("query", "") or ""),
            top_k=int(args.get("top_k", 5) or 5),
            neighbor_budget=int(args.get("neighbor_budget", 12) or 12),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("enterprise_workflow_query output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(query_result, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        result = {
            "ok": True,
            "action": name,
            "query_result": query_result,
            "summary": {
                "readiness": query_result.get("readiness"),
                "score": query_result.get("score"),
                "insight_count": len(query_result.get("insights", []))
                if isinstance(query_result.get("insights"), list)
                else 0,
                "anchor_count": len(query_result.get("graph_rag", {}).get("anchor_nodes", []))
                if isinstance(query_result.get("graph_rag"), dict)
                else 0,
                "subgraph_node_count": len(query_result.get("graph_rag", {}).get("subgraph", {}).get("nodes", []))
                if isinstance(query_result.get("graph_rag"), dict)
                and isinstance(query_result.get("graph_rag", {}).get("subgraph"), dict)
                else 0,
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "command_api_plan":
        plan = build_command_api_plan(
            goal=str(args.get("goal", "大项目级 AgentOS CommandAPI") or "大项目级 AgentOS CommandAPI"),
            focus=str(args.get("focus", "large_project_cohesion") or "large_project_cohesion"),
            include_cypher=bool(args.get("include_cypher", True)),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("command_api_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        result = {
            "ok": True,
            "action": name,
            "plan": plan,
            "summary": {
                "command_count": len(plan.get("commands", [])) if isinstance(plan.get("commands"), list) else 0,
                "bounded_context_count": len(plan.get("bounded_contexts", []))
                if isinstance(plan.get("bounded_contexts"), list)
                else 0,
                "anti_looseness_rule_count": len(plan.get("anti_looseness_rules", []))
                if isinstance(plan.get("anti_looseness_rules"), list)
                else 0,
                "graph_node_count": len(plan.get("graph_projection", {}).get("nodes", []))
                if isinstance(plan.get("graph_projection"), dict)
                else 0,
                "cypher_bytes": len(str(plan.get("cypher_seed", "")).encode("utf-8")),
                "mermaid_bytes": len(str(plan.get("mermaid", "")).encode("utf-8")),
            },
        }
        if write_result is not None:
            result["write"] = write_result
        return result

    if name == "skill_runtime_plan":
        plan = build_skill_runtime_plan(
            str(args.get("goal", "获取 SkillBundle 并防止任务/格式/思维链幻化") or "获取 SkillBundle 并防止任务/格式/思维链幻化"),
            required_skill_ids=_string_tuple_arg(args, "required_skill_ids"),
            explicit_scope=_string_tuple_arg(args, "explicit_scope"),
            output_schema_name=str(args.get("output_schema_name", "guarded_agent_response.v1") or "guarded_agent_response.v1"),
            sample_output=args.get("sample_output"),
            known_evidence_ids=_string_tuple_arg(args, "known_evidence_ids"),
        )
        output_path = _optional_path_arg(workspace, args, "output_path")
        write_result: dict[str, Any] | None = None
        if output_path is not None:
            try:
                output_path.relative_to(workspace.resolve())
            except ValueError as exc:
                raise ExecutorError("skill_runtime_plan output_path must stay inside workspace") from exc
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_text = json.dumps(plan, ensure_ascii=False, indent=2)
            output_path.write_text(output_text, encoding="utf-8")
            write_result = {"path": str(output_path), "bytes": len(output_text.encode("utf-8"))}
        selected = plan.get("bundle", {}).get("selected_skills", []) if isinstance(plan.get("bundle"), dict) else []
        validation = plan.get("validation", {}) if isinstance(plan.get("validation"), dict) else {}
        return {
            "ok": bool(validation.get("ok", True)),
            "action": name,
            "plan": plan,
            "summary": {
                "selected_skill_count": len(selected),
                "validation_ok": validation.get("ok", None),
                "violation_count": len(validation.get("violations", [])) if isinstance(validation.get("violations"), list) else 0,
            },
            "write": write_result or {},
        }

    if name == "local_training_run":
        output_dir = _optional_path_arg(workspace, args, "output_dir") or (workspace / "local_training_runs")
        try:
            output_dir.relative_to(workspace.resolve())
        except ValueError as exc:
            raise ExecutorError("local_training_run output_dir must stay inside workspace") from exc
        middle_trace_paths = tuple(
            path if path.is_absolute() else (workspace / path)
            for path in _path_tuple_arg(args, "middle_trace_paths")
        )
        github_ranking_paths = tuple(
            path if path.is_absolute() else (workspace / path)
            for path in _path_tuple_arg(args, "github_ranking_paths")
        )
        manifest = run_local_training(
            target=str(args.get("target", "both") or "both"),
            output_dir=output_dir,
            middle_trace_paths=middle_trace_paths,
            github_ranking_paths=github_ranking_paths,
            epochs=int(args.get("epochs", 30) or 30),
        )
        result = {
            "ok": True,
            "action": name,
            "manifest": manifest,
            "summary": {
                "target": manifest.get("target"),
                "output_dir": manifest.get("output_dir"),
                "middle_status": manifest.get("results", {}).get("middle_model", {}).get("status")
                if isinstance(manifest.get("results"), dict)
                else "",
                "github_status": manifest.get("results", {}).get("github_evaluator", {}).get("status")
                if isinstance(manifest.get("results"), dict)
                else "",
                "middle_examples": manifest.get("results", {}).get("middle_model", {}).get("training_examples", 0)
                if isinstance(manifest.get("results"), dict)
                else 0,
                "github_examples": manifest.get("results", {}).get("github_evaluator", {}).get("training_examples", 0)
                if isinstance(manifest.get("results"), dict)
                else 0,
            },
        }
        return result

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
