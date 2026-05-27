"""主循环 — plan → decide → execute → analyze → fix；everything-claude 主控。

函数流程图：
    run_agent_loop(goal, workspace, prompts_dir, brain, config, resume)
      -> AppConfig / ExecutionLimits 初始化
      -> 加载或创建 ProjectState
      -> build_run_id() 生成单次运行 run_id
      -> loop_start 事件
      -> 每轮循环：
           sync_file_list()
           build_workspace_index()
           plan()
           run_context_chain()                 # skill/rag/mcp 上下文分链
           decision.evaluate_decision_policy()  # 策略层候选动作打分
           emit_event() 追加带 run_id 的 plan/context_enriched events
           brain.decide()
           parse_action()
           ship gate 预检查（finish 前）
           executor.run_action()
           state.update_from_result()
           decision.compute_reward_signal()
           decision.build_decision_trace()
           append execute/finish events
           quality / health / safety gate
           analyze_exec_result() -> brain.fix()
      -> 保存 state/session/events

你可以继续练算法/工程化的点：
    1. 调度策略：现在是单循环顺序决策；可以做 stage-aware priority queue。
    2. 失败恢复：现在按计数进入 investigate；可以按错误类型聚类和置信度升级。
    3. 质量评分：当前 health/review/wtf 是启发式；可以训练或调参成多指标评分器。
    4. 事件压缩：事件写全量摘要；可以做窗口化采样、关键事件抽取和因果链追踪。
    5. 策略层：decision policy 现在是启发式；可以替换为 bandit/RL，但不能绕过 executor。
    6. 事件关联：run_id 已能串起单次运行；可以继续加 sequence/parent_run_id 支持恢复链。
    7. 上下文预算：可以根据 token 预算动态决定 RAG、history、stderr 的保留比例。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.chains.context import ContextChainInput, run_context_chain
from agent.config import AppConfig
from agent.core import executor as ex
from agent.core.brain import AgentBrain
from agent.core.executor import ExecutionLimits
from agent.core.feedback import analyze_exec_result
from agent.core.governance import action_governance
from agent.core.planner import plan
from agent.decision import (
    build_decision_trace,
    compute_reward_signal,
    evaluate_decision_policy,
    update_policy_state,
)
from agent.memory.project_state import ProjectState
from agent.memory.session import SessionMemory
from agent.observability import get_logger
from agent.pipeline.quality import calculate_health_score, calculate_wtf_likelihood, should_stop_fixing
from agent.pipeline.stages import StageId
from agent.recorder import append_event, build_run_id
from agent.tools.workspace_index import build_workspace_index

_LOG = get_logger("loop")


def _ship_gate_error(state: ProjectState, min_review_score: float, min_health_score: float) -> str | None:
    if state.current_stage != StageId.SHIP.value:
        return None
    if not (state.progress.startswith("run_ok") or state.progress.startswith("production_check_ok")):
        return "ship gate failed: last run_command or production_check is not successful"
    review_score = float(state.quality.get("review_score") or 0.0)
    health_score = float(state.quality.get("health_score") or 0.0)
    if review_score < min_review_score:
        return f"ship gate failed: review_score {review_score:.2f} < {min_review_score:.2f}"
    if health_score < min_health_score:
        return f"ship gate failed: health_score {health_score:.2f} < {min_health_score:.2f}"
    return None


def _build_investigate_handoff(state: ProjectState) -> dict[str, Any]:
    recent_errors = state.errors[-3:]
    stderr_samples: list[str] = []
    combined = []
    for e in recent_errors:
        text = str(e.get("stderr", "")).strip()
        msg = str(e.get("message", "")).strip()
        if msg:
            combined.append(msg.lower())
        if text:
            stderr_samples.append(text[:240])
            combined.append(text.lower())
    joined = "\n".join(combined)
    recommendations = [
        "collect_minimal_repro",
        "inspect_recent_diff",
        "run_targeted_debug_command",
    ]
    if "modulenotfounderror" in joined or "no module named" in joined or "importerror" in joined:
        recommendations = [
            "verify_dependencies_and_import_paths",
            "run_pip_show_or_pip_list_for_missing_module",
            "confirm_venv_and_python_interpreter_alignment",
        ]
    elif "not recognized as an internal or external command" in joined or "command not found" in joined:
        recommendations = [
            "verify_command_exists_in_path",
            "switch_to_python_m_invocation_if_possible",
            "add_tool_install_or_fallback_command",
        ]
    elif "syntaxerror" in joined or "indentationerror" in joined:
        recommendations = [
            "open_and_review_recently_generated_file",
            "run_python_m_py_compile_on_target_files",
            "apply_minimal_syntax_fix_then_rerun",
        ]
    elif "[timeout]" in joined or "timed out" in joined:
        recommendations = [
            "reduce_command_scope_for_repro",
            "increase_timeout_or_split_steps",
            "capture_intermediate_logs_before_timeout",
        ]
    return {
        "reason": "investigate_required",
        "command_failures": int(state.counters.get("command_failures", 0)),
        "fix_attempts": int(state.counters.get("fix_attempts", 0)),
        "recent_error_messages": [str(e.get("message", "")) for e in recent_errors],
        "recent_stderr_samples": stderr_samples,
        "recommended_next_actions": recommendations,
    }


def _plan_summary(plan_dict: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"stage": str(plan_dict.get("stage", ""))}
    tasks = plan_dict.get("tasks")
    if isinstance(tasks, list) and tasks:
        hint_lines = []
        for x in tasks:
            s = str(x)
            if ("rag_hints" in s) or ("skill_hints" in s) or ("mcp 工具" in s):
                hint_lines.append(s[:120])
        if hint_lines:
            summary["context_task_hints"] = hint_lines[:3]
            summary["context_hint_count"] = len(hint_lines)
    meta = plan_dict.get("meta")
    if isinstance(meta, dict):
        rec = meta.get("recommended_next_actions")
        if isinstance(rec, list) and rec:
            summary["priority_guidance"] = [str(x) for x in rec[:3]]
    return summary


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "action": str(result.get("action", "")),
        "ok": bool(result.get("ok", False)),
    }
    if "returncode" in result:
        try:
            summary["returncode"] = int(result.get("returncode"))
        except (TypeError, ValueError):
            pass
    if "duration_ms" in result:
        summary["duration_ms"] = result.get("duration_ms")
    if "error_code" in result:
        summary["error_code"] = result.get("error_code")
        summary["retryable"] = bool(result.get("retryable", False))
        if result.get("recommended_action"):
            summary["recommended_action"] = result.get("recommended_action")
    preflight = result.get("preflight")
    if isinstance(preflight, dict):
        summary["preflight_status"] = preflight.get("status")
        summary["risk_level"] = preflight.get("risk_level")
        supervisor = preflight.get("supervisor")
        if isinstance(supervisor, dict):
            summary["supervisor_status"] = supervisor.get("status")
            summary["supervisor_risk_level"] = supervisor.get("risk_level")
            summary["sandbox_recommended"] = bool(supervisor.get("sandbox_recommended", False))
            summary["sandbox_required"] = bool(supervisor.get("sandbox_required", False))
    stderr = str(result.get("stderr", "")).strip()
    if stderr:
        summary["stderr_head"] = stderr[:180]
    if summary["action"] == "production_check":
        report = result.get("report", {})
        if isinstance(report, dict):
            rep_summary = report.get("summary", {})
            if isinstance(rep_summary, dict):
                summary["python_files"] = rep_summary.get("python_files")
                summary["compile_failures"] = rep_summary.get("compile_failures")
                summary["pytest_ran"] = rep_summary.get("pytest_ran")
            checks = report.get("checks", [])
            if isinstance(checks, list):
                failed = [str(c.get("name", "")) for c in checks if isinstance(c, dict) and not c.get("ok", False)]
                if failed:
                    summary["failed_checks"] = failed[:5]
    reason = result.get("reason")
    if isinstance(reason, str) and reason:
        summary["reason"] = reason
    evaluation = result.get("evaluation")
    if isinstance(evaluation, dict):
        if "overall_score" in evaluation:
            summary["evaluation_score"] = evaluation.get("overall_score")
        if "grade" in evaluation:
            summary["evaluation_grade"] = evaluation.get("grade")
    if summary["action"] == "context_pv_plan":
        pv_summary = result.get("summary")
        if isinstance(pv_summary, dict):
            for key in ("manifest_id", "total_tokens", "slice_count", "placement_count", "k8s_doc_count"):
                if key in pv_summary:
                    summary[key] = pv_summary.get(key)
    if summary["action"] == "resilience_plan":
        resilience_summary = result.get("summary")
        if isinstance(resilience_summary, dict):
            for key in ("surface", "threat_level", "payment_enabled", "chaos_drill_count"):
                if key in resilience_summary:
                    summary[key] = resilience_summary.get(key)
    if summary["action"] == "business_rule_compile":
        rule_summary = result.get("summary")
        if isinstance(rule_summary, dict):
            for key in ("domain", "entity_count", "state_count", "transition_count", "api_count", "finding_count"):
                if key in rule_summary:
                    summary[key] = rule_summary.get(key)
    if summary["action"] == "automation_scorecard_plan":
        scorecard_summary = result.get("summary")
        if isinstance(scorecard_summary, dict):
            for key in ("metric_count", "anti_cheat_count", "evidence_findings", "experiment_demands", "observation_days"):
                if key in scorecard_summary:
                    summary[key] = scorecard_summary.get(key)
    if summary["action"] == "graph_runtime_plan":
        graph_summary = result.get("summary")
        if isinstance(graph_summary, dict):
            for key in ("modification_count", "runtime_node_count", "runtime_edge_count", "graph_label_count", "graph_query_count"):
                if key in graph_summary:
                    summary[key] = graph_summary.get(key)
    if summary["action"] == "graph_events_ingest":
        ingest_summary = result.get("summary")
        if isinstance(ingest_summary, dict):
            for key in ("event_count", "run_count", "node_count", "edge_count", "failed_actions", "human_reviews", "graph_rag_anchor_count"):
                if key in ingest_summary:
                    summary[key] = ingest_summary.get(key)
    if summary["action"] == "operations_readiness_plan":
        ops_summary = result.get("summary")
        if isinstance(ops_summary, dict):
            for key in (
                "health_status",
                "ready",
                "monitoring_metric_count",
                "alert_count",
                "healthy_agent_count",
                "reassignment_count",
                "dead_letter_count",
            ):
                if key in ops_summary:
                    summary[key] = ops_summary.get(key)
    if summary["action"] == "cloud_native_deep_dive_plan":
        cloud_summary = result.get("summary")
        if isinstance(cloud_summary, dict):
            for key in (
                "focus",
                "source_count",
                "collapse_route_count",
                "etcd_algorithm_count",
                "scheduler_extension_count",
                "storage_controller_count",
                "prometheus_metric_count",
            ):
                if key in cloud_summary:
                    summary[key] = cloud_summary.get(key)
    if summary["action"] == "enterprise_workflow_compile":
        workflow_summary = result.get("summary")
        if isinstance(workflow_summary, dict):
            for key in (
                "workflow_name",
                "node_count",
                "edge_count",
                "score",
                "readiness",
                "finding_count",
                "high_risk_count",
                "delivery_stage_count",
                "graph_node_count",
                "graph_edge_count",
                "cypher_bytes",
                "mermaid_bytes",
            ):
                if key in workflow_summary:
                    summary[key] = workflow_summary.get(key)
    if summary["action"] == "enterprise_workflow_query":
        workflow_query_summary = result.get("summary")
        if isinstance(workflow_query_summary, dict):
            for key in ("readiness", "score", "insight_count", "anchor_count", "subgraph_node_count"):
                if key in workflow_query_summary:
                    summary[key] = workflow_query_summary.get(key)
    if summary["action"] == "command_api_plan":
        command_summary = result.get("summary")
        if isinstance(command_summary, dict):
            for key in (
                "command_count",
                "bounded_context_count",
                "anti_looseness_rule_count",
                "graph_node_count",
                "cypher_bytes",
                "mermaid_bytes",
            ):
                if key in command_summary:
                    summary[key] = command_summary.get(key)
    if summary["action"] == "local_training_run":
        training_summary = result.get("summary")
        if isinstance(training_summary, dict):
            for key in ("target", "output_dir", "middle_status", "github_status", "middle_examples", "github_examples"):
                if key in training_summary:
                    summary[key] = training_summary.get(key)
    return summary


def _stopped_summary(state: ProjectState, reason: str) -> dict[str, Any]:
    return {
        "action": "stopped",
        "reason": reason,
        "stage": state.current_stage,
        "command_failures": int(state.counters.get("command_failures", 0)),
        "fix_attempts": int(state.counters.get("fix_attempts", 0)),
        "wtf_likelihood": int(state.quality.get("wtf_likelihood", 0)),
    }


def _ship_gate_blocked_summary(state: ProjectState, detail: str) -> dict[str, Any]:
    return {
        "action": "ship_gate_blocked",
        "stage": state.current_stage,
        "detail": detail[:200],
        "review_score": state.quality.get("review_score"),
        "health_score": state.quality.get("health_score"),
    }


def _action_summary(action_obj: dict[str, Any]) -> dict[str, Any]:
    action_name = str(action_obj.get("action", ""))
    governance = action_governance(action_name)
    summary: dict[str, Any] = {
        "action": action_name,
        "risk_level": governance.risk_level,
        "required_permissions": list(governance.permissions),
    }
    args = action_obj.get("args")
    if not isinstance(args, dict):
        return summary
    if summary["action"] in ("write_file", "read_file"):
        path = args.get("path")
        if isinstance(path, str):
            summary["path"] = path
    elif summary["action"] == "run_command":
        cmd = args.get("command")
        if isinstance(cmd, str):
            summary["command_head"] = cmd[:120]
        if "timeout" in args:
            summary["timeout"] = args.get("timeout")
    elif summary["action"] == "k8s_sandbox_plan":
        cmd = args.get("command")
        if isinstance(cmd, str):
            summary["command_head"] = cmd[:120]
        for key in ("namespace", "image", "network", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
    elif summary["action"] == "context_pv_plan":
        text = args.get("text")
        if isinstance(text, str):
            summary["text_chars"] = len(text)
        query = args.get("query")
        if isinstance(query, str):
            summary["query_head"] = query[:120]
        for key in ("namespace", "tenant", "output_path", "version"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
    elif summary["action"] == "resilience_plan":
        for key in ("surface", "payment_provider", "threat_level", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
        if "payment_enabled" in args:
            summary["payment_enabled"] = bool(args.get("payment_enabled"))
    elif summary["action"] == "business_rule_compile":
        rules = args.get("rules")
        if isinstance(rules, str):
            summary["rules_head"] = rules[:120]
            summary["rules_chars"] = len(rules)
        for key in ("domain_hint", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
    elif summary["action"] == "automation_scorecard_plan":
        for key in ("output_path",):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
        for key in ("demand_count", "observation_days"):
            if key in args:
                summary[key] = args.get(key)
    elif summary["action"] == "graph_runtime_plan":
        goal = args.get("goal")
        if isinstance(goal, str):
            summary["goal_head"] = goal[:120]
        output_path = args.get("output_path")
        if isinstance(output_path, str):
            summary["output_path"] = output_path
        if "include_cypher" in args:
            summary["include_cypher"] = bool(args.get("include_cypher"))
    elif summary["action"] == "graph_events_ingest":
        for key in ("events_path", "query", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key if key != "query" else "query_head"] = value[:120] if key == "query" else value
        if "include_cypher" in args:
            summary["include_cypher"] = bool(args.get("include_cypher"))
    elif summary["action"] == "operations_readiness_plan":
        for key in ("service_name", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
        if "replicas" in args:
            summary["replicas"] = args.get("replicas")
    elif summary["action"] == "cloud_native_deep_dive_plan":
        for key in ("focus", "kubernetes_version", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
        if "include_sources" in args:
            summary["include_sources"] = bool(args.get("include_sources"))
    elif summary["action"] == "enterprise_workflow_compile":
        for key in ("goal", "domain", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key if key != "goal" else "goal_head"] = value[:120] if key == "goal" else value
        if "include_delivery_plan" in args:
            summary["include_delivery_plan"] = bool(args.get("include_delivery_plan"))
        if isinstance(args.get("spec"), dict):
            nodes = args["spec"].get("nodes")
            summary["spec_node_count"] = len(nodes) if isinstance(nodes, list) else 0
    elif summary["action"] == "enterprise_workflow_query":
        for key in ("query", "goal", "domain", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key if key not in {"query", "goal"} else f"{key}_head"] = value[:120]
        for key in ("top_k", "neighbor_budget"):
            if key in args:
                summary[key] = args.get(key)
    elif summary["action"] == "command_api_plan":
        for key in ("goal", "focus", "output_path"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key if key != "goal" else "goal_head"] = value[:120] if key == "goal" else value
        if "include_cypher" in args:
            summary["include_cypher"] = bool(args.get("include_cypher"))
    elif summary["action"] == "local_training_run":
        for key in ("target", "output_dir"):
            value = args.get(key)
            if isinstance(value, str):
                summary[key] = value
        for key in ("middle_trace_paths", "github_ranking_paths"):
            value = args.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
        if "epochs" in args:
            summary["epochs"] = args.get("epochs")
    elif summary["action"] == "list_files":
        pat = args.get("pattern")
        if isinstance(pat, str):
            summary["pattern"] = pat
    elif summary["action"] in ("web_search", "research_synthesize"):
        query = args.get("query")
        if isinstance(query, str):
            summary["query_head"] = query[:120]
        if "use_web" in args:
            summary["use_web"] = bool(args.get("use_web"))
        if "use_llm" in args:
            summary["use_llm"] = bool(args.get("use_llm"))
    elif summary["action"] == "training_prepare":
        out_dir = args.get("output_dir")
        if isinstance(out_dir, str):
            summary["output_dir"] = out_dir
        fmt = args.get("dataset_format")
        if isinstance(fmt, str):
            summary["dataset_format"] = fmt
    elif summary["action"] == "github_crawl_profile":
        out_dir = args.get("output_dir")
        if isinstance(out_dir, str):
            summary["output_dir"] = out_dir
        query = args.get("query")
        if isinstance(query, str):
            summary["query_head"] = query[:120]
        if "github" in args:
            summary["github"] = bool(args.get("github"))
    elif summary["action"] == "finish":
        reason = args.get("reason")
        if isinstance(reason, str):
            summary["reason"] = reason
    return summary


def run_agent_loop(
    goal: str,
    workspace: Path,
    prompts_dir: Path,
    brain: AgentBrain,
    config: AppConfig | None = None,
    *,
    resume: bool = False,
) -> ProjectState:
    cfg = config or AppConfig.from_env()
    policy_extra = Path(cfg.policy_extra_path).resolve() if cfg.policy_extra_path else None
    limits = ExecutionLimits(
        max_write_bytes=cfg.max_write_bytes,
        default_command_timeout=cfg.default_command_timeout,
        max_command_timeout=cfg.max_command_timeout,
        max_command_output_chars=cfg.max_command_output_chars,
        policy_extra_path=policy_extra,
        granted_permissions=frozenset(cfg.granted_permissions),
        confirmed_actions=frozenset(cfg.confirmed_actions),
    )
    workspace.mkdir(parents=True, exist_ok=True)
    state_path = workspace / ".agent_state.json"
    session_path = workspace / ".agent_session.jsonl"
    events_path = (workspace / ".agent_events.jsonl") if cfg.event_log else None
    run_id = build_run_id(str(workspace.resolve()))

    def emit_event(kind: str, payload: dict[str, Any]) -> None:
        row_payload = dict(payload)
        row_payload["run_id"] = run_id
        append_event(events_path, kind, row_payload)

    def record_decision_outcome(
        *,
        iteration: int,
        policy_decision: dict[str, Any],
        action_obj: dict[str, Any],
        result: dict[str, Any],
        before_state: dict[str, Any],
    ) -> dict[str, Any]:
        reward = compute_reward_signal(before_state, state, result)
        executed_action = str(action_obj.get("action", result.get("action", "")))
        state.policy = update_policy_state(
            state.policy,
            executed_action=executed_action,
            reward_signal=reward,
            decision=policy_decision,
        )
        trace = build_decision_trace(
            iteration=iteration,
            policy_decision=policy_decision,
            action_obj=action_obj,
            reward_signal=reward,
        )
        emit_event("reward_signal", {"iteration": iteration, "reward": reward})
        emit_event("decision_trace", {"iteration": iteration, "trace": trace})
        return reward

    if resume and state_path.exists():
        state = ProjectState.load(state_path)
        if cfg.resume_clear_errors:
            state.errors = []
        _LOG.info("resume loaded state progress=%s errors=%s", state.progress, len(state.errors))
    else:
        state = ProjectState(current_stage="", progress="init")
    state.goal = goal

    session = SessionMemory()
    emit_event("loop_start", {"goal": goal, "resume": resume})

    last_result: dict[str, Any] | None = None
    done = False
    stopped_reason: str | None = None
    for i in range(cfg.max_agent_iterations):
        state.sync_file_list(workspace)
        state.structure = build_workspace_index(workspace)
        plan_dict = plan(goal, state, prompts_dir, cfg)
        context_result = run_context_chain(
            ContextChainInput(
                structure=state.structure,
                workspace=workspace,
                goal=goal,
                plan=plan_dict,
                state=state.to_dict(),
                config=cfg,
            )
        )
        state.structure = context_result.structure
        state.current_stage = str(plan_dict.get("stage", ""))
        policy_decision = evaluate_decision_policy(goal, plan_dict, state)
        state.structure["decision_policy"] = policy_decision
        session.append("planner", json.dumps(plan_dict, ensure_ascii=False), meta={"iteration": i})
        emit_event(
            "plan",
            {"iteration": i, "plan": plan_dict, "plan_summary": _plan_summary(plan_dict)},
        )
        emit_event(
            "context_enriched",
            {"iteration": i, "summary": context_result.summary},
        )
        emit_event("decision_policy", {"iteration": i, "decision": policy_decision})
        if (
            state.current_stage == StageId.INVESTIGATE.value
            and int(state.counters.get("command_failures", 0)) >= 3
        ):
            state.structure["investigate_handoff"] = _build_investigate_handoff(state)
            state.progress = "stopped:investigate_required"
            stopped_reason = "investigate_required"
            state.last_iteration = i
            state.save(state_path)
            emit_event(
                "stopped",
                {
                    "reason": "investigate_required",
                    "command_failures": int(state.counters.get("command_failures", 0)),
                    "result_summary": _stopped_summary(state, "investigate_required"),
                },
            )
            break

        action_line = brain.decide(goal, plan_dict, state, last_result, session=session)
        session.append("agent", action_line, meta={"iteration": i})
        action_obj = ex.parse_action(action_line)
        before_decision_state = state.to_dict()
        emit_event(
            "decide",
            {
                "iteration": i,
                "action_line": action_line,
                "action_summary": _action_summary(action_obj),
                "token_usage": dict(getattr(brain, "last_usage", {}) or {}),
            },
        )
        if action_obj.get("action") == "finish":
            ship_gate_err = _ship_gate_error(
                state,
                cfg.ship_gate_min_review_score,
                cfg.ship_gate_min_health_score,
            )
            if ship_gate_err:
                state.record_error("ship_gate", ship_gate_err, "")
                state.progress = "ship_gate:blocked"
                last_result = {
                    "ok": False,
                    "action": "finish",
                    "reason": "ship_gate_failed",
                    "detail": ship_gate_err,
                }
                session.append("ship_gate", json.dumps(last_result, ensure_ascii=False), meta={"iteration": i})
                record_decision_outcome(
                    iteration=i,
                    policy_decision=policy_decision,
                    action_obj=action_obj,
                    result=last_result,
                    before_state=before_decision_state,
                )
                emit_event(
                    "ship_gate_blocked",
                    {
                        "iteration": i,
                        "detail": ship_gate_err,
                        "result_summary": _ship_gate_blocked_summary(state, ship_gate_err),
                    },
                )
                state.last_iteration = i
                state.save(state_path)
                continue
            last_result = ex.run_action_guarded(workspace, action_obj, limits=limits)
            state.update_from_result(last_result)
            record_decision_outcome(
                iteration=i,
                policy_decision=policy_decision,
                action_obj=action_obj,
                result=last_result,
                before_state=before_decision_state,
            )
            state.last_iteration = i
            state.save(state_path)
            if cfg.session_log_jsonl:
                session.append_jsonl(session_path)
            emit_event(
                "finish",
                {"iteration": i, "result": last_result, "result_summary": _result_summary(last_result)},
            )
            done = True
            _LOG.info("finished at iteration %s reason=%s", i, last_result.get("reason"))
            break

        last_result = ex.run_action_guarded(workspace, action_obj, limits=limits)
        state.update_from_result(last_result)
        record_decision_outcome(
            iteration=i,
            policy_decision=policy_decision,
            action_obj=action_obj,
            result=last_result,
            before_state=before_decision_state,
        )
        session.append("executor", json.dumps(last_result, ensure_ascii=False), meta={"iteration": i})
        emit_event(
            "execute",
            {"iteration": i, "result": last_result, "result_summary": _result_summary(last_result)},
        )

        if state.current_stage == StageId.REVIEW.value:
            review_score = max(
                0.0,
                10.0
                - min(float(state.counters.get("command_failures", 0)) * 0.8, 5.0)
                - min(float(len(state.errors)) * 0.3, 2.0),
            )
            state.record_quality(review_score=review_score)
        elif state.current_stage == StageId.QA.value:
            verification_ok = state.progress.startswith("run_ok") or state.progress.startswith("production_check_ok")
            health_score = calculate_health_score(
                test_pass_rate=100.0 if verification_ok else 0.0,
                critical_high_count=0 if verification_ok else 1,
                review_score=float(state.quality.get("review_score") or 0.0),
                wtf_likelihood=int(state.quality.get("wtf_likelihood", 0)),
            )
            state.record_quality(health_score=health_score)

        err = analyze_exec_result(last_result)
        if err:
            state.record_error("executor", err, str(last_result.get("stderr", "")))
            state.counters["fix_attempts"] = int(state.counters.get("fix_attempts", 0)) + 1
            state.quality["wtf_likelihood"] = calculate_wtf_likelihood(
                fix_count=int(state.counters.get("fix_attempts", 0)),
                revert_count=int(state.counters.get("reverts", 0)),
                files_touched=len(state.files),
                remaining_low_only=False,
            )
            if should_stop_fixing(int(state.quality.get("wtf_likelihood", 0)), int(state.counters.get("fix_attempts", 0))):
                state.progress = "stopped:safety_gate"
                stopped_reason = "safety_gate"
                state.last_iteration = i
                state.save(state_path)
                emit_event(
                    "stopped",
                    {
                        "reason": "safety_gate",
                        "wtf_likelihood": state.quality.get("wtf_likelihood", 0),
                        "result_summary": _stopped_summary(state, "safety_gate"),
                    },
                )
                break
            fix_line = brain.fix(err, goal, plan_dict, state, session=session)
            if fix_line != action_line:
                fix_policy_decision = evaluate_decision_policy(goal, plan_dict, state)
                state.structure["decision_policy"] = fix_policy_decision
                emit_event("decision_policy", {"iteration": i, "mode": "fix", "decision": fix_policy_decision})
                session.append("agent_fix", fix_line, meta={"iteration": i})
                fix_obj = ex.parse_action(fix_line)
                emit_event(
                    "fix",
                    {
                        "iteration": i,
                        "fix_line": fix_line,
                        "action_summary": _action_summary(fix_obj),
                        "token_usage": dict(getattr(brain, "last_usage", {}) or {}),
                    },
                )
                if fix_obj.get("action") != "finish":
                    before_fix_state = state.to_dict()
                    last_result = ex.run_action_guarded(workspace, fix_obj, limits=limits)
                    state.update_from_result(last_result)
                    record_decision_outcome(
                        iteration=i,
                        policy_decision=fix_policy_decision,
                        action_obj=fix_obj,
                        result=last_result,
                        before_state=before_fix_state,
                    )
                    session.append("executor_fix", json.dumps(last_result, ensure_ascii=False), meta={"iteration": i})
                    emit_event(
                        "execute_fix",
                        {"iteration": i, "result": last_result, "result_summary": _result_summary(last_result)},
                    )

        state.last_iteration = i
        state.save(state_path)
        if cfg.session_log_jsonl:
            session.append_jsonl(session_path)
        _LOG.debug("iteration %s stage=%s progress=%s", i, state.current_stage, state.progress)

    if not done:
        if stopped_reason is None:
            state.progress = "stopped:max_iterations"
            stopped_reason = "max_iterations"
        state.save(state_path)
        if cfg.session_log_jsonl:
            session.append_jsonl(session_path)
        emit_event(
            "stopped",
            {"reason": stopped_reason, "result_summary": _stopped_summary(state, str(stopped_reason))},
        )
        _LOG.warning("stopped with reason=%s after %s iterations", stopped_reason, cfg.max_agent_iterations)
    return state
