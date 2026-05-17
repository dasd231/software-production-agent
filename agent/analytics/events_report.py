"""Summarize .agent_events.jsonl into human-readable diagnostics.

函数流程图：
    load_events(path)
      -> 逐行读取 JSONL
      -> 跳过空行
      -> 只保留 dict 事件

    build_events_summary(rows)
      -> 聚合事件种类/schema/stage path
      -> 聚合 run_id，判断一个日志是否混有多次运行
      -> 聚合 decision_policy / reward_signal / decision_trace
      -> 聚合 context/RAG 使用情况
      -> 聚合失败动作和最近失败样本
      -> 从 ts 计算 first_ts/last_ts/duration_seconds
      -> _diagnose() 推断 severity/root_cause/next commands
      -> 返回稳定 summary dict

    summarize_events_file(path, output)
      -> load_events()
      -> build_events_summary()
      -> render_summary_text/markdown 或 json.dumps()

    compare_events_files(current, baseline, output)
      -> 分别 build_events_summary()
      -> compare_summaries()
      -> render_comparison_text/markdown 或 json.dumps()

    should_fail_inspection()/build_gate_result()
      -> 将 summary/comparison 转成 CI gate 判断和稳定 JSON

    history 系列函数
      -> append_history_row()
      -> load/filter/build/render history summary
      -> 聚合 latest_runs / failure_reasons / status streak / duration / regression 趋势
      -> should_fail_history()/build_history_gate_result()

你可以继续练算法/工程化的点：
    1. 诊断算法：_diagnose 现在是关键词规则；可以改成多信号打分和优先级解释。
    2. 对比算法：worsened 现在看 severity/context/RAG；可以加入耗时、失败密度、重试次数。
    3. 趋势算法：history 现在按 severity 单步回归；可以做滑动窗口、分支/标签基线和异常检测。
    4. 失败归因：failure_reasons 现在是简单频次；可以做原因聚类、根因归并和置信度排序。
    5. 连续状态：streak 现在只看末尾状态；可以扩展最长失败 streak、恢复时间和波动率。
    6. 运行聚合：run_id 现在只做唯一值列表；可以按 run_id 分段计算每次运行摘要。
    7. 决策学习：reward 现在只做均值；可以按 action/strategy 做 value estimate 和置信区间。
    8. 最近样本：latest_runs 现在是固定 Top5；可以做时间窗口采样和失败优先采样。
    9. 报告渲染：text/markdown 重复较多；可以抽表格/section renderer，减少格式漂移。
    10. 事件 schema：现在是宽松 dict；可以引入版本化事件 DTO，提升长期兼容性。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any


def _event_ts(row: dict[str, Any]) -> float | None:
    try:
        ts = float(row.get("ts"))
    except (TypeError, ValueError):
        return None
    return ts if ts >= 0 else None


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"events file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def build_events_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    schema_versions: dict[str, int] = {}
    run_ids: list[str] = []
    seen_run_ids: set[str] = set()
    final_reason = ""
    final_progress = ""
    stages: list[str] = []
    guidance_hits = 0
    context_hint_plan_hits = 0
    context_hint_task_count = 0
    stage_context_usage: dict[str, dict[str, int]] = {}
    decision_strategy_counts: dict[str, int] = {}
    policy_selected_counts: dict[str, int] = {}
    bandit_selector_counts: dict[str, int] = {}
    selected_bandit_score_total = 0.0
    selected_bandit_score_count = 0
    top_bandit_bonus_total = 0.0
    top_bandit_bonus_count = 0
    decision_alignment = {"aligned": 0, "diverged": 0}
    reward_count = 0
    reward_total = 0.0
    last_rewards: list[dict[str, Any]] = []
    stderr_heads: list[str] = []
    last_failures: list[dict[str, Any]] = []
    failure_action_counts: dict[str, int] = {}
    rag_path_counts: dict[str, int] = {}
    rag_truncated_total = 0
    first_ts: float | None = None
    last_ts: float | None = None

    for r in rows:
        ts = _event_ts(r)
        if ts is not None:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        kind = str(r.get("kind", ""))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        sv = str(r.get("schema_version", ""))
        schema_versions[sv] = schema_versions.get(sv, 0) + 1
        run_id = str(r.get("run_id", "")).strip()
        if run_id and run_id not in seen_run_ids:
            seen_run_ids.add(run_id)
            run_ids.append(run_id)
        if kind == "plan":
            ps = r.get("plan_summary", {})
            if isinstance(ps, dict):
                st = ps.get("stage")
                if isinstance(st, str) and st:
                    stages.append(st)
                    bucket = stage_context_usage.setdefault(st, {"plans": 0, "context_hits": 0})
                    bucket["plans"] += 1
                if isinstance(ps.get("priority_guidance"), list):
                    guidance_hits += 1
                cth = ps.get("context_task_hints")
                if isinstance(cth, list) and cth:
                    context_hint_plan_hits += 1
                    context_hint_task_count += len(cth)
                    if isinstance(st, str) and st:
                        stage_context_usage.setdefault(st, {"plans": 0, "context_hits": 0})["context_hits"] += 1
        if kind == "decision_policy":
            decision = r.get("decision", {})
            if isinstance(decision, dict):
                strategy = str(decision.get("strategy", "")).strip()
                if strategy:
                    decision_strategy_counts[strategy] = decision_strategy_counts.get(strategy, 0) + 1
                selected = str(decision.get("selected_action", "")).strip()
                if selected:
                    policy_selected_counts[selected] = policy_selected_counts.get(selected, 0) + 1
                selector = decision.get("selector", {})
                if isinstance(selector, dict):
                    version = str(selector.get("selector_version", "")).strip()
                    if version:
                        bandit_selector_counts[version] = bandit_selector_counts.get(version, 0) + 1
                    try:
                        selected_score = float(selector.get("selected_bandit_score", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        selected_score = 0.0
                    if selected_score:
                        selected_bandit_score_total += selected_score
                        selected_bandit_score_count += 1
                candidates = decision.get("candidate_actions", [])
                if isinstance(candidates, list) and candidates:
                    first = candidates[0]
                    if isinstance(first, dict):
                        try:
                            bonus = float(first.get("bandit_bonus", 0.0) or 0.0)
                        except (TypeError, ValueError):
                            bonus = 0.0
                        if bonus:
                            top_bandit_bonus_total += bonus
                            top_bandit_bonus_count += 1
        if kind == "decision_trace":
            trace = r.get("trace", {})
            if isinstance(trace, dict):
                if bool(trace.get("aligned_with_policy", False)):
                    decision_alignment["aligned"] += 1
                else:
                    decision_alignment["diverged"] += 1
        if kind == "reward_signal":
            reward = r.get("reward", {})
            if isinstance(reward, dict):
                try:
                    total = float(reward.get("total", 0.0) or 0.0)
                except (TypeError, ValueError):
                    total = 0.0
                reward_count += 1
                reward_total += total
                last_rewards.append(
                    {
                        "action": str(reward.get("action", "")),
                        "total": round(total, 3),
                        "ok": bool(reward.get("ok", False)),
                        "progress_after": str(reward.get("progress_after", "")),
                    }
                )
        if kind == "context_enriched":
            summary = r.get("summary", {})
            if isinstance(summary, dict):
                paths = summary.get("rag_paths")
                if isinstance(paths, list):
                    for p in paths:
                        path = str(p).strip()
                        if path:
                            rag_path_counts[path] = rag_path_counts.get(path, 0) + 1
                try:
                    rag_truncated_total += int(summary.get("rag_truncated", 0) or 0)
                except (TypeError, ValueError):
                    pass
        if kind == "stopped":
            final_reason = str(r.get("reason", final_reason))
            rs = r.get("result_summary", {})
            if isinstance(rs, dict):
                sh = rs.get("stderr_head")
                if isinstance(sh, str) and sh.strip():
                    stderr_heads.append(sh.strip())
        if kind == "finish":
            rs = r.get("result_summary", {})
            if isinstance(rs, dict):
                final_reason = str(rs.get("reason", final_reason))
                sh = rs.get("stderr_head")
                if isinstance(sh, str) and sh.strip():
                    stderr_heads.append(sh.strip())
            final_progress = "finished"
        if kind in ("execute", "execute_fix"):
            rs = r.get("result_summary", {})
            if isinstance(rs, dict):
                sh = rs.get("stderr_head")
                if isinstance(sh, str) and sh.strip():
                    stderr_heads.append(sh.strip())
                ok = bool(rs.get("ok", True))
                action = str(rs.get("action", ""))
                if not ok:
                    failure_action_counts[action] = failure_action_counts.get(action, 0) + 1
                    last_failures.append(
                        {
                            "kind": kind,
                            "action": action,
                            "returncode": rs.get("returncode"),
                            "stderr_head": sh if isinstance(sh, str) else "",
                            "ts": r.get("ts"),
                        }
                    )

    if not final_progress and final_reason:
        final_progress = f"stopped:{final_reason}"
    if not final_progress:
        final_progress = "unknown"

    failure_actions_top = sorted(
        [{"action": k, "count": v} for k, v in failure_action_counts.items()],
        key=lambda x: (-int(x["count"]), str(x["action"])),
    )[:5]
    rag_paths_top = sorted(
        [{"path": k, "count": v} for k, v in rag_path_counts.items()],
        key=lambda x: (-int(x["count"]), str(x["path"])),
    )[:10]
    diagnostic = _diagnose(summary_reason=final_reason, stderr_heads=stderr_heads, by_kind=by_kind)
    duration = round(max(0.0, (last_ts or 0.0) - (first_ts or 0.0)), 2) if first_ts is not None and last_ts is not None else 0.0
    return {
        "total_events": len(rows),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "duration_seconds": duration,
        "run_count": len(run_ids),
        "run_ids": run_ids,
        "schema_versions": schema_versions,
        "by_kind": dict(sorted(by_kind.items(), key=lambda x: x[0])),
        "stage_path": stages,
        "priority_guidance_plan_hits": guidance_hits,
        "context_hint_plan_hits": context_hint_plan_hits,
        "context_hint_task_count": context_hint_task_count,
        "stage_context_usage": stage_context_usage,
        "decision_strategy_counts": dict(sorted(decision_strategy_counts.items(), key=lambda x: (-x[1], x[0]))),
        "policy_selected_counts": dict(sorted(policy_selected_counts.items(), key=lambda x: (-x[1], x[0]))),
        "bandit_selector_counts": dict(sorted(bandit_selector_counts.items(), key=lambda x: (-x[1], x[0]))),
        "avg_selected_bandit_score": round(selected_bandit_score_total / selected_bandit_score_count, 3)
        if selected_bandit_score_count
        else 0.0,
        "avg_top_bandit_bonus": round(top_bandit_bonus_total / top_bandit_bonus_count, 3)
        if top_bandit_bonus_count
        else 0.0,
        "decision_alignment": decision_alignment,
        "reward_count": reward_count,
        "avg_reward": round(reward_total / reward_count, 3) if reward_count else 0.0,
        "last_rewards": last_rewards[-5:],
        "rag_paths_top": rag_paths_top,
        "rag_truncated_total": rag_truncated_total,
        "failure_actions_top": failure_actions_top,
        "last_failures": last_failures[-5:],
        "final_progress": final_progress,
        "final_reason": final_reason,
        "diagnostic": diagnostic,
    }


def _diagnose(summary_reason: str, stderr_heads: list[str], by_kind: dict[str, int]) -> dict[str, Any]:
    reason = (summary_reason or "").lower()
    joined = "\n".join(stderr_heads).lower()
    severity = "info"
    root_cause = "unknown"
    recommendations = [
        "python -m agent.main --inspect-events <path> --inspect-format json",
        "python -m pytest tests -q",
    ]
    if "modulenotfounderror" in joined or "no module named" in joined or "importerror" in joined:
        severity = "high"
        root_cause = "dependency_or_import_path"
        recommendations = [
            "pip show <missing-module>",
            "pip install -r requirements.txt",
            "python -c \"import <missing_module>\"",
        ]
    elif "syntaxerror" in joined or "indentationerror" in joined:
        severity = "high"
        root_cause = "syntax_generation_error"
        recommendations = [
            "python -m py_compile <file.py>",
            "python -m pytest tests -q",
        ]
    elif "command not found" in joined or "not recognized as an internal or external command" in joined:
        severity = "high"
        root_cause = "missing_cli_tool"
        recommendations = [
            "where <command>",
            "python -m <module>  # prefer python -m fallback",
        ]
    elif "[timeout]" in joined or "timed out" in joined:
        severity = "medium"
        root_cause = "timeout_or_long_running_step"
        recommendations = [
            "python -m agent.main --demo --resume --max-iter 5",
            "set AGENT_CMD_TIMEOUT=240",
        ]
    elif "safety_gate" in reason:
        severity = "critical"
        root_cause = "fix_loop_instability"
        recommendations = [
            "python -m agent.main --demo --resume --resume-clear-errors --max-iter 5",
            "python -m agent.main --inspect-events <path>",
            "rg -n \"Traceback|Error|Exception\" <workspace>",
        ]
    elif "ship_gate_failed" in reason or by_kind.get("ship_gate_blocked", 0) > 0:
        severity = "high"
        root_cause = "ship_gate_quality_block"
        recommendations = [
            "python -m agent.main --demo --resume --max-iter 10",
            "set AGENT_SHIP_MIN_HEALTH_SCORE=6.5  # tune only if intentional",
            "set AGENT_SHIP_MIN_REVIEW_SCORE=5.5  # tune only if intentional",
        ]
    elif "investigate_required" in reason:
        severity = "high"
        root_cause = "repeated_command_failures"
        recommendations = [
            "python -m agent.main --inspect-events <path>",
            "python -m agent.main --demo --resume --max-iter 5",
            "rg -n \"ModuleNotFoundError|ImportError|SyntaxError|timeout\" <workspace>",
        ]
    elif "max_iterations" in reason:
        severity = "medium"
        root_cause = "insufficient_convergence"
        recommendations = [
            "python -m agent.main --demo --resume --max-iter 80",
            "python -m agent.main --inspect-events <path>",
        ]
    return {
        "severity": severity,
        "root_cause": root_cause,
        "next_command_templates": recommendations,
    }


def render_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Event Report")
    lines.append(f"total_events: {summary.get('total_events', 0)}")
    lines.append(f"duration_seconds: {float(summary.get('duration_seconds', 0.0) or 0.0):.2f}")
    lines.append(f"run_count: {int(summary.get('run_count', 0) or 0)}")
    run_ids = summary.get("run_ids", [])
    if isinstance(run_ids, list) and run_ids:
        lines.append("run_ids: " + ", ".join(str(x) for x in run_ids[:10]))
    else:
        lines.append("run_ids: (none)")
    lines.append(f"final_progress: {summary.get('final_progress', '')}")
    lines.append(f"final_reason: {summary.get('final_reason', '')}")
    lines.append(f"priority_guidance_plan_hits: {summary.get('priority_guidance_plan_hits', 0)}")
    lines.append(f"context_hint_plan_hits: {summary.get('context_hint_plan_hits', 0)}")
    lines.append(f"context_hint_task_count: {summary.get('context_hint_task_count', 0)}")
    lines.append(f"reward_count: {summary.get('reward_count', 0)}")
    lines.append(f"avg_reward: {float(summary.get('avg_reward', 0.0) or 0.0):.3f}")
    diag = summary.get("diagnostic", {})
    if isinstance(diag, dict):
        lines.append(f"severity: {diag.get('severity', 'info')}")
        lines.append(f"root_cause: {diag.get('root_cause', 'unknown')}")
        lines.append("next_command_templates:")
        cmds = diag.get("next_command_templates", [])
        if isinstance(cmds, list):
            for c in cmds:
                lines.append(f"  - {c}")
    lines.append("schema_versions:")
    for k, v in dict(summary.get("schema_versions", {})).items():
        lines.append(f"  - {k}: {v}")
    lines.append("event_counts:")
    for k, v in dict(summary.get("by_kind", {})).items():
        lines.append(f"  - {k}: {v}")
    lines.append("decision_strategy_counts:")
    dsc = summary.get("decision_strategy_counts", {})
    if isinstance(dsc, dict) and dsc:
        for k, v in dsc.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  - (none)")
    lines.append("policy_selected_counts:")
    psc = summary.get("policy_selected_counts", {})
    if isinstance(psc, dict) and psc:
        for k, v in psc.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  - (none)")
    lines.append("bandit_selector_counts:")
    bsc = summary.get("bandit_selector_counts", {})
    if isinstance(bsc, dict) and bsc:
        for k, v in bsc.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  - (none)")
    lines.append(f"avg_selected_bandit_score: {float(summary.get('avg_selected_bandit_score', 0.0) or 0.0):.3f}")
    lines.append(f"avg_top_bandit_bonus: {float(summary.get('avg_top_bandit_bonus', 0.0) or 0.0):.3f}")
    align = summary.get("decision_alignment", {})
    if isinstance(align, dict):
        lines.append(f"decision_alignment: aligned={align.get('aligned', 0)}, diverged={align.get('diverged', 0)}")
    lines.append("last_rewards:")
    lr = summary.get("last_rewards", [])
    if isinstance(lr, list) and lr:
        for row in lr:
            if isinstance(row, dict):
                lines.append(
                    f"  - action={row.get('action', '')} total={float(row.get('total', 0.0) or 0.0):.3f} ok={row.get('ok')} progress={row.get('progress_after', '')}"
                )
    else:
        lines.append("  - (none)")
    stage_path = summary.get("stage_path", [])
    if isinstance(stage_path, list) and stage_path:
        lines.append("stage_path: " + " -> ".join(str(x) for x in stage_path))
    else:
        lines.append("stage_path: (empty)")
    lines.append("stage_context_usage:")
    scu = summary.get("stage_context_usage", {})
    if isinstance(scu, dict) and scu:
        for st, row in sorted(scu.items(), key=lambda x: str(x[0])):
            if isinstance(row, dict):
                plans = int(row.get("plans", 0) or 0)
                hits = int(row.get("context_hits", 0) or 0)
                rate = (hits / plans * 100.0) if plans > 0 else 0.0
                lines.append(f"  - {st}: plans={plans}, context_hits={hits}, hit_rate={rate:.1f}%")
    else:
        lines.append("  - (none)")
    lines.append("rag_paths_top:")
    rpt = summary.get("rag_paths_top", [])
    if isinstance(rpt, list) and rpt:
        for row in rpt:
            if isinstance(row, dict):
                lines.append(f"  - {row.get('path', '')}: {row.get('count', 0)}")
    else:
        lines.append("  - (none)")
    lines.append(f"rag_truncated_total: {summary.get('rag_truncated_total', 0)}")
    lines.append("failure_actions_top:")
    fat = summary.get("failure_actions_top", [])
    if isinstance(fat, list) and fat:
        for row in fat:
            if isinstance(row, dict):
                lines.append(f"  - {row.get('action', '')}: {row.get('count', 0)}")
    else:
        lines.append("  - (none)")
    lines.append("last_failures:")
    lf = summary.get("last_failures", [])
    if isinstance(lf, list) and lf:
        for row in lf:
            if isinstance(row, dict):
                lines.append(
                    f"  - [{row.get('kind', '')}] {row.get('action', '')} rc={row.get('returncode', '')} stderr={str(row.get('stderr_head', ''))[:100]}"
                )
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def render_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Event Report")
    lines.append("")
    lines.append(f"- **Total events:** {summary.get('total_events', 0)}")
    lines.append(f"- **Duration seconds:** {float(summary.get('duration_seconds', 0.0) or 0.0):.2f}")
    lines.append(f"- **Run count:** {int(summary.get('run_count', 0) or 0)}")
    lines.append(f"- **Final progress:** `{summary.get('final_progress', '')}`")
    lines.append(f"- **Final reason:** `{summary.get('final_reason', '')}`")
    lines.append(f"- **Priority guidance plan hits:** {summary.get('priority_guidance_plan_hits', 0)}")
    lines.append(f"- **Context hint plan hits:** {summary.get('context_hint_plan_hits', 0)}")
    lines.append(f"- **Context hint task count:** {summary.get('context_hint_task_count', 0)}")
    lines.append(f"- **Reward count:** {summary.get('reward_count', 0)}")
    lines.append(f"- **Average reward:** {float(summary.get('avg_reward', 0.0) or 0.0):.3f}")
    diag = summary.get("diagnostic", {})
    if isinstance(diag, dict):
        lines.append(f"- **Severity:** `{diag.get('severity', 'info')}`")
        lines.append(f"- **Root cause:** `{diag.get('root_cause', 'unknown')}`")
    lines.append("")
    lines.append("## Run IDs")
    run_ids = summary.get("run_ids", [])
    if isinstance(run_ids, list) and run_ids:
        for run_id in run_ids[:10]:
            lines.append(f"- `{run_id}`")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Event Counts")
    by_kind = summary.get("by_kind", {})
    if isinstance(by_kind, dict) and by_kind:
        for k, v in by_kind.items():
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Decision Policy")
    dsc = summary.get("decision_strategy_counts", {})
    if isinstance(dsc, dict) and dsc:
        lines.append("Strategies:")
        for k, v in dsc.items():
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("Strategies: (none)")
    psc = summary.get("policy_selected_counts", {})
    if isinstance(psc, dict) and psc:
        lines.append("Selected actions:")
        for k, v in psc.items():
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("Selected actions: (none)")
    bsc = summary.get("bandit_selector_counts", {})
    if isinstance(bsc, dict) and bsc:
        lines.append("Bandit selectors:")
        for k, v in bsc.items():
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("Bandit selectors: (none)")
    lines.append(f"- Average selected bandit score: {float(summary.get('avg_selected_bandit_score', 0.0) or 0.0):.3f}")
    lines.append(f"- Average top bandit bonus: {float(summary.get('avg_top_bandit_bonus', 0.0) or 0.0):.3f}")
    align = summary.get("decision_alignment", {})
    if isinstance(align, dict):
        lines.append(f"- Alignment: aligned={align.get('aligned', 0)}, diverged={align.get('diverged', 0)}")
    lines.append("")
    lines.append("## Rewards")
    lr = summary.get("last_rewards", [])
    if isinstance(lr, list) and lr:
        for row in lr:
            if isinstance(row, dict):
                lines.append(
                    f"- `{row.get('action', '')}` total={float(row.get('total', 0.0) or 0.0):.3f} ok=`{row.get('ok')}` progress=`{row.get('progress_after', '')}`"
                )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Stage Path")
    stage_path = summary.get("stage_path", [])
    if isinstance(stage_path, list) and stage_path:
        lines.append("`" + " -> ".join(str(x) for x in stage_path) + "`")
    else:
        lines.append("(empty)")
    lines.append("")
    lines.append("## Stage Context Usage")
    scu = summary.get("stage_context_usage", {})
    if isinstance(scu, dict) and scu:
        for st, row in sorted(scu.items(), key=lambda x: str(x[0])):
            if isinstance(row, dict):
                plans = int(row.get("plans", 0) or 0)
                hits = int(row.get("context_hits", 0) or 0)
                rate = (hits / plans * 100.0) if plans > 0 else 0.0
                lines.append(f"- `{st}`: plans={plans}, context_hits={hits}, hit_rate={rate:.1f}%")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## RAG Context")
    rpt = summary.get("rag_paths_top", [])
    if isinstance(rpt, list) and rpt:
        for row in rpt:
            if isinstance(row, dict):
                lines.append(f"- `{row.get('path', '')}` x {row.get('count', 0)}")
    else:
        lines.append("- (none)")
    lines.append(f"- Truncated snippets: {summary.get('rag_truncated_total', 0)}")
    lines.append("")
    lines.append("## Top Failure Actions")
    fat = summary.get("failure_actions_top", [])
    if isinstance(fat, list) and fat:
        for row in fat:
            if isinstance(row, dict):
                lines.append(f"- `{row.get('action', '')}` x {row.get('count', 0)}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Recent Failures")
    lf = summary.get("last_failures", [])
    if isinstance(lf, list) and lf:
        for row in lf:
            if isinstance(row, dict):
                lines.append(
                    f"- `{row.get('kind', '')}` `{row.get('action', '')}` rc={row.get('returncode', '')} `{str(row.get('stderr_head', ''))[:100]}`"
                )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Next Command Templates")
    cmds = diag.get("next_command_templates", []) if isinstance(diag, dict) else []
    if isinstance(cmds, list) and cmds:
        for c in cmds:
            lines.append(f"- `{c}`")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def summarize_events_file(path: Path, output: str = "text") -> str:
    rows = load_events(path)
    summary = build_events_summary(rows)
    if output == "json":
        return json.dumps(summary, ensure_ascii=False, indent=2)
    if output == "markdown":
        return render_summary_markdown(summary)
    return render_summary_text(summary)


def compare_summaries(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    def _as_int(v: Any) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def _as_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    current_total = _as_int(current.get("total_events"))
    baseline_total = _as_int(baseline.get("total_events"))
    current_duration = round(_as_float(current.get("duration_seconds")), 2)
    baseline_duration = round(_as_float(baseline.get("duration_seconds")), 2)
    c_by = dict(current.get("by_kind", {}))
    b_by = dict(baseline.get("by_kind", {}))
    keys = sorted(set(c_by.keys()) | set(b_by.keys()))
    by_kind_delta: dict[str, int] = {}
    for k in keys:
        by_kind_delta[k] = _as_int(c_by.get(k)) - _as_int(b_by.get(k))

    def _sev_rank(name: str) -> int:
        return {"info": 0, "medium": 1, "high": 2, "critical": 3}.get(str(name), 0)

    c_diag = current.get("diagnostic", {}) if isinstance(current.get("diagnostic"), dict) else {}
    b_diag = baseline.get("diagnostic", {}) if isinstance(baseline.get("diagnostic"), dict) else {}
    c_sev = str(c_diag.get("severity", "info"))
    b_sev = str(b_diag.get("severity", "info"))
    sev_delta = _sev_rank(c_sev) - _sev_rank(b_sev)
    if sev_delta < 0:
        sev_trend = "improved"
    elif sev_delta > 0:
        sev_trend = "worsened"
    else:
        sev_trend = "unchanged"

    c_stage_ctx = current.get("stage_context_usage", {})
    b_stage_ctx = baseline.get("stage_context_usage", {})
    stage_keys = []
    if isinstance(c_stage_ctx, dict):
        stage_keys.extend([str(k) for k in c_stage_ctx.keys()])
    if isinstance(b_stage_ctx, dict):
        stage_keys.extend([str(k) for k in b_stage_ctx.keys()])
    stage_keys = sorted(set(stage_keys))
    stage_context_delta: dict[str, dict[str, int]] = {}
    for st in stage_keys:
        c_row = c_stage_ctx.get(st, {}) if isinstance(c_stage_ctx, dict) else {}
        b_row = b_stage_ctx.get(st, {}) if isinstance(b_stage_ctx, dict) else {}
        c_plans = int(c_row.get("plans", 0) or 0) if isinstance(c_row, dict) else 0
        b_plans = int(b_row.get("plans", 0) or 0) if isinstance(b_row, dict) else 0
        c_hits = int(c_row.get("context_hits", 0) or 0) if isinstance(c_row, dict) else 0
        b_hits = int(b_row.get("context_hits", 0) or 0) if isinstance(b_row, dict) else 0
        stage_context_delta[st] = {
            "plans_delta": c_plans - b_plans,
            "context_hits_delta": c_hits - b_hits,
        }

    def _rag_counts(summary: dict[str, Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        rows = summary.get("rag_paths_top", [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                path = str(row.get("path", "")).strip()
                if path:
                    out[path] = _as_int(row.get("count"))
        return out

    c_rag = _rag_counts(current)
    b_rag = _rag_counts(baseline)
    rag_path_delta = {
        p: c_rag.get(p, 0) - b_rag.get(p, 0)
        for p in sorted(set(c_rag.keys()) | set(b_rag.keys()))
    }

    comp = {
        "event_delta_total": current_total - baseline_total,
        "duration_seconds_current": current_duration,
        "duration_seconds_baseline": baseline_duration,
        "duration_seconds_delta": round(current_duration - baseline_duration, 2),
        "by_kind_delta": by_kind_delta,
        "final_progress_current": current.get("final_progress", ""),
        "final_progress_baseline": baseline.get("final_progress", ""),
        "final_reason_current": current.get("final_reason", ""),
        "final_reason_baseline": baseline.get("final_reason", ""),
        "severity_current": c_sev,
        "severity_baseline": b_sev,
        "severity_trend": sev_trend,
        "root_cause_current": c_diag.get("root_cause", "unknown"),
        "root_cause_baseline": b_diag.get("root_cause", "unknown"),
        "stage_path_current": current.get("stage_path", []),
        "stage_path_baseline": baseline.get("stage_path", []),
        "stage_context_delta": stage_context_delta,
        "rag_path_delta": rag_path_delta,
        "rag_truncated_delta": _as_int(current.get("rag_truncated_total"))
        - _as_int(baseline.get("rag_truncated_total")),
    }
    comp["worsened_reasons"] = _comparison_worsened_reasons(comp)
    return comp


def stage_context_missing_stages(summary: dict[str, Any] | None, required_stages: list[str] | None = None) -> list[str]:
    if not summary:
        return []
    stage_stats = summary.get("stage_context_usage", {})
    if not isinstance(stage_stats, dict):
        return []
    targets = [str(x).strip().lower() for x in (required_stages or ["coding", "fixing", "investigate"]) if str(x).strip()]
    missing: list[str] = []
    for st in targets:
        row = stage_stats.get(st, {})
        if not isinstance(row, dict):
            continue
        plans = int(row.get("plans", 0) or 0)
        hits = int(row.get("context_hits", 0) or 0)
        if plans > 0 and hits <= 0:
            missing.append(st)
    return missing


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _comparison_worsened_reasons(comparison: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if str(comparison.get("severity_trend", "")).lower() == "worsened":
        reasons.append("severity_worsened")
    scd = comparison.get("stage_context_delta", {})
    if isinstance(scd, dict):
        for stage, row in sorted(scd.items(), key=lambda x: str(x[0])):
            if not isinstance(row, dict):
                continue
            if _safe_int(row.get("context_hits_delta", 0)) < 0:
                reasons.append(f"context_hits_down:{stage}")
    rpd = comparison.get("rag_path_delta", {})
    if isinstance(rpd, dict):
        for path, delta in sorted(rpd.items(), key=lambda x: str(x[0])):
            if _safe_int(delta) < 0:
                reasons.append(f"rag_path_down:{path}")
    if _safe_int(comparison.get("rag_truncated_delta", 0)) > 0:
        reasons.append("rag_truncated_up")
    return reasons


def _comparison_context_worsened(comparison: dict[str, Any]) -> bool:
    return bool(_comparison_worsened_reasons(comparison))


def inspection_failure_reasons(
    *,
    mode: str,
    failed: bool,
    summary: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
    required_stages: list[str] | None = None,
) -> list[str]:
    if not failed:
        return []
    m = (mode or "").strip().lower()
    if m == "critical":
        diag = summary.get("diagnostic", {}) if summary and isinstance(summary.get("diagnostic"), dict) else {}
        if str(diag.get("severity", "info")).lower() == "critical":
            return ["severity_critical"]
        return ["critical_gate_failed"]
    if m == "worsened":
        if not comparison:
            return ["worsened"]
        reasons = comparison.get("worsened_reasons", _comparison_worsened_reasons(comparison))
        if isinstance(reasons, list) and reasons:
            return [str(x) for x in reasons]
        return ["worsened"]
    if m == "no_context_usage":
        return ["no_context_usage"]
    if m == "stage_context_missing":
        missing = stage_context_missing_stages(summary, required_stages)
        return [f"stage_context_missing:{stage}" for stage in missing] or ["stage_context_missing"]
    return [m] if m else []


def render_comparison_text(comp: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Event Comparison Report")
    lines.append(f"severity: {comp.get('severity_baseline', 'info')} -> {comp.get('severity_current', 'info')} ({comp.get('severity_trend', 'unchanged')})")
    lines.append(f"final_progress: {comp.get('final_progress_baseline', '')} -> {comp.get('final_progress_current', '')}")
    lines.append(f"final_reason: {comp.get('final_reason_baseline', '')} -> {comp.get('final_reason_current', '')}")
    lines.append(f"event_delta_total: {comp.get('event_delta_total', 0)}")
    lines.append(f"duration_seconds_delta: {float(comp.get('duration_seconds_delta', 0.0) or 0.0):+.2f}")
    lines.append("by_kind_delta:")
    by_kind = comp.get("by_kind_delta", {})
    if isinstance(by_kind, dict):
        for k, v in by_kind.items():
            lines.append(f"  - {k}: {v:+d}")
    base_path = comp.get("stage_path_baseline", [])
    cur_path = comp.get("stage_path_current", [])
    lines.append("stage_path_baseline: " + (" -> ".join(str(x) for x in base_path) if base_path else "(empty)"))
    lines.append("stage_path_current: " + (" -> ".join(str(x) for x in cur_path) if cur_path else "(empty)"))
    lines.append("stage_context_delta:")
    scd = comp.get("stage_context_delta", {})
    if isinstance(scd, dict) and scd:
        for st, row in sorted(scd.items(), key=lambda x: str(x[0])):
            if isinstance(row, dict):
                lines.append(
                    f"  - {st}: plans_delta={int(row.get('plans_delta', 0)):+d}, context_hits_delta={int(row.get('context_hits_delta', 0)):+d}"
                )
    else:
        lines.append("  - (none)")
    lines.append("rag_path_delta:")
    rpd = comp.get("rag_path_delta", {})
    if isinstance(rpd, dict) and rpd:
        for path, delta in sorted(rpd.items(), key=lambda x: str(x[0])):
            lines.append(f"  - {path}: {int(delta):+d}")
    else:
        lines.append("  - (none)")
    lines.append(f"rag_truncated_delta: {int(comp.get('rag_truncated_delta', 0) or 0):+d}")
    reasons = comp.get("worsened_reasons", [])
    lines.append("worsened_reasons:")
    if isinstance(reasons, list) and reasons:
        for reason in reasons:
            lines.append(f"  - {reason}")
    else:
        lines.append("  - (none)")
    lines.append(f"root_cause: {comp.get('root_cause_baseline', 'unknown')} -> {comp.get('root_cause_current', 'unknown')}")
    return "\n".join(lines)


def render_comparison_markdown(comp: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Event Comparison Report")
    lines.append("")
    lines.append(
        f"- **Severity:** `{comp.get('severity_baseline', 'info')}` -> `{comp.get('severity_current', 'info')}` ({comp.get('severity_trend', 'unchanged')})"
    )
    lines.append(f"- **Final progress:** `{comp.get('final_progress_baseline', '')}` -> `{comp.get('final_progress_current', '')}`")
    lines.append(f"- **Final reason:** `{comp.get('final_reason_baseline', '')}` -> `{comp.get('final_reason_current', '')}`")
    lines.append(f"- **Event delta total:** {comp.get('event_delta_total', 0)}")
    lines.append(f"- **Duration seconds delta:** {float(comp.get('duration_seconds_delta', 0.0) or 0.0):+.2f}")
    lines.append(f"- **Root cause:** `{comp.get('root_cause_baseline', 'unknown')}` -> `{comp.get('root_cause_current', 'unknown')}`")
    lines.append("")
    lines.append("## Event Delta by Kind")
    by_kind = comp.get("by_kind_delta", {})
    if isinstance(by_kind, dict) and by_kind:
        for k, v in by_kind.items():
            lines.append(f"- `{k}`: {int(v):+d}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Stage Path")
    base_path = comp.get("stage_path_baseline", [])
    cur_path = comp.get("stage_path_current", [])
    lines.append("- Baseline: " + ("`" + " -> ".join(str(x) for x in base_path) + "`" if base_path else "(empty)"))
    lines.append("- Current: " + ("`" + " -> ".join(str(x) for x in cur_path) + "`" if cur_path else "(empty)"))
    lines.append("")
    lines.append("## Stage Context Delta")
    scd = comp.get("stage_context_delta", {})
    if isinstance(scd, dict) and scd:
        for st, row in sorted(scd.items(), key=lambda x: str(x[0])):
            if isinstance(row, dict):
                lines.append(
                    f"- `{st}`: plans_delta={int(row.get('plans_delta', 0)):+d}, context_hits_delta={int(row.get('context_hits_delta', 0)):+d}"
                )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## RAG Context Delta")
    rpd = comp.get("rag_path_delta", {})
    if isinstance(rpd, dict) and rpd:
        for path, delta in sorted(rpd.items(), key=lambda x: str(x[0])):
            lines.append(f"- `{path}`: {int(delta):+d}")
    else:
        lines.append("- (none)")
    lines.append(f"- Truncated snippets delta: {int(comp.get('rag_truncated_delta', 0) or 0):+d}")
    lines.append("")
    lines.append("## Worsened Reasons")
    reasons = comp.get("worsened_reasons", [])
    if isinstance(reasons, list) and reasons:
        for reason in reasons:
            lines.append(f"- `{reason}`")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def compare_events_files(current_path: Path, baseline_path: Path, output: str = "text") -> str:
    current = build_events_summary(load_events(current_path))
    baseline = build_events_summary(load_events(baseline_path))
    comp = compare_summaries(current, baseline)
    if output == "json":
        return json.dumps(comp, ensure_ascii=False, indent=2)
    if output == "markdown":
        return render_comparison_markdown(comp)
    return render_comparison_text(comp)


def should_fail_inspection(
    *,
    mode: str,
    summary: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
    required_stages: list[str] | None = None,
) -> bool:
    m = (mode or "").strip().lower()
    if not m:
        return False
    if m == "critical":
        diag = {}
        if summary and isinstance(summary.get("diagnostic"), dict):
            diag = summary.get("diagnostic", {})
        sev = str(diag.get("severity", "info")).lower()
        return sev == "critical"
    if m == "worsened":
        if not comparison:
            return False
        return _comparison_context_worsened(comparison)
    if m == "no_context_usage":
        if not summary:
            return False
        by_kind = summary.get("by_kind", {})
        if not isinstance(by_kind, dict):
            return False
        plan_count = int(by_kind.get("plan", 0) or 0)
        if plan_count <= 0:
            return False
        return int(summary.get("context_hint_plan_hits", 0) or 0) <= 0
    if m == "stage_context_missing":
        return len(stage_context_missing_stages(summary, required_stages)) > 0
    raise ValueError(f"unsupported inspect fail mode: {mode}")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_report_metadata(
    *,
    current_path: Path,
    baseline_path: Path | None,
    inspect_format: str,
    fail_mode: str,
) -> dict[str, Any]:
    now = time.time()
    token = f"{now}:{current_path}:{baseline_path}:{inspect_format}:{fail_mode}:{uuid.uuid4()}"
    analysis_id = hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]
    meta: dict[str, Any] = {
        "schema_version": "1",
        "analysis_id": analysis_id,
        "generated_at": now,
        "inspect_format": inspect_format,
        "fail_mode": fail_mode or "",
        "current_events_path": str(current_path),
        "current_events_sha256": file_sha256(current_path),
    }
    if baseline_path is not None:
        meta["baseline_events_path"] = str(baseline_path)
        meta["baseline_events_sha256"] = file_sha256(baseline_path)
    return meta


def save_report_with_metadata(save_path: Path, report_text: str, metadata: dict[str, Any]) -> Path:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(report_text, encoding="utf-8")
    sidecar = save_path.with_suffix(save_path.suffix + ".meta.json")
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar


def build_gate_result(
    *,
    analysis_id: str,
    fail_mode: str,
    failed: bool,
    summary: dict[str, Any] | None,
    comparison: dict[str, Any] | None,
    required_stages: list[str] | None = None,
) -> dict[str, Any]:
    severity = "info"
    reason = ""
    final_progress = ""
    duration_seconds = 0.0
    if summary and isinstance(summary.get("diagnostic"), dict):
        diag = summary.get("diagnostic", {})
        severity = str(diag.get("severity", "info"))
        reason = str(summary.get("final_reason", ""))
        final_progress = str(summary.get("final_progress", ""))
        duration_seconds = round(_safe_float(summary.get("duration_seconds")), 2)
    if comparison:
        severity = str(comparison.get("severity_current", severity))
        reason = str(comparison.get("final_reason_current", reason))
        final_progress = str(comparison.get("final_progress_current", final_progress))
        duration_seconds = round(_safe_float(comparison.get("duration_seconds_current")), 2)
    out: dict[str, Any] = {
        "schema_version": "1",
        "analysis_id": analysis_id,
        "gate_mode": fail_mode or "",
        "status": "fail" if failed else "pass",
        "severity": severity,
        "reason": reason,
        "final_progress": final_progress,
        "duration_seconds": duration_seconds,
        "failure_reasons": inspection_failure_reasons(
            mode=fail_mode,
            failed=failed,
            summary=summary,
            comparison=comparison,
            required_stages=required_stages,
        ),
    }
    if comparison:
        out["severity_trend"] = comparison.get("severity_trend", "")
        out["worsened_reasons"] = comparison.get("worsened_reasons", _comparison_worsened_reasons(comparison))
        out["stage_context_delta"] = comparison.get("stage_context_delta", {})
        out["rag_path_delta"] = comparison.get("rag_path_delta", {})
        out["rag_truncated_delta"] = comparison.get("rag_truncated_delta", 0)
        out["duration_seconds_delta"] = comparison.get("duration_seconds_delta", 0.0)
    if (fail_mode or "").strip().lower() == "stage_context_missing":
        out["missing_context_stages"] = stage_context_missing_stages(summary, required_stages)
    return out


def save_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_history_row(
    *,
    gate_result: dict[str, Any],
    label: str,
    baseline_path: Path | None,
    report_path: Path | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "ts": time.time(),
        "analysis_id": gate_result.get("analysis_id", ""),
        "status": gate_result.get("status", ""),
        "severity": gate_result.get("severity", ""),
        "reason": gate_result.get("reason", ""),
        "final_progress": gate_result.get("final_progress", ""),
        "duration_seconds": round(_safe_float(gate_result.get("duration_seconds")), 2),
        "failure_reasons": gate_result.get("failure_reasons", []),
        "gate_mode": gate_result.get("gate_mode", ""),
        "label": label,
        "has_baseline": baseline_path is not None,
        "baseline_path": str(baseline_path) if baseline_path is not None else "",
        "report_path": str(report_path) if report_path is not None else "",
    }


def load_history_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"history file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def filter_history_rows(rows: list[dict[str, Any]], label: str = "", last_n: int = 0) -> list[dict[str, Any]]:
    out = rows
    if label.strip():
        target = label.strip()
        out = [r for r in out if str(r.get("label", "")) == target]
    if last_n > 0:
        out = out[-last_n:]
    return out


def build_history_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    status_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    label_counts: dict[str, int] = {}
    failure_reason_counts: dict[str, int] = {}
    regressions: list[dict[str, Any]] = []
    durations: list[float] = []
    slowest_candidates: list[dict[str, Any]] = []
    latest_candidates: list[dict[str, Any]] = []

    def _rank(sev: str) -> int:
        return {"info": 0, "medium": 1, "high": 2, "critical": 3}.get(sev, 0)

    prev_sev = "info"
    for i, r in enumerate(rows):
        status = str(r.get("status", ""))
        sev = str(r.get("severity", "info"))
        label = str(r.get("label", ""))
        duration = round(max(0.0, _safe_float(r.get("duration_seconds"))), 2)
        raw_failure_reasons = r.get("failure_reasons", [])
        failure_reasons = [str(x) for x in raw_failure_reasons if str(x).strip()] if isinstance(raw_failure_reasons, list) else []
        latest_candidates.append(
            {
                "index": i,
                "analysis_id": r.get("analysis_id", ""),
                "status": status,
                "severity": sev,
                "label": label,
                "duration_seconds": duration,
                "reason": r.get("reason", ""),
                "failure_reasons": failure_reasons,
                "ts": r.get("ts"),
            }
        )
        if duration > 0:
            durations.append(duration)
            slowest_candidates.append(
                {
                    "index": i,
                    "analysis_id": r.get("analysis_id", ""),
                    "status": status,
                    "severity": sev,
                    "label": label,
                    "duration_seconds": duration,
                    "reason": r.get("reason", ""),
                }
            )
        status_counts[status] = status_counts.get(status, 0) + 1
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        if label:
            label_counts[label] = label_counts.get(label, 0) + 1
        counted_failure_reason = False
        for reason in failure_reasons:
            key = reason.strip()
            if key:
                failure_reason_counts[key] = failure_reason_counts.get(key, 0) + 1
                counted_failure_reason = True
        if status == "fail" and not counted_failure_reason:
            fallback_reason = str(r.get("reason", "")).strip()
            if fallback_reason:
                key = f"final_reason:{fallback_reason}"
                failure_reason_counts[key] = failure_reason_counts.get(key, 0) + 1
        if i > 0 and _rank(sev) > _rank(prev_sev):
            regressions.append(
                {
                    "index": i,
                    "analysis_id": r.get("analysis_id", ""),
                    "from": prev_sev,
                    "to": sev,
                    "reason": r.get("reason", ""),
                    "label": r.get("label", ""),
                    "ts": r.get("ts"),
                }
            )
        prev_sev = sev

    pass_count = status_counts.get("pass", 0)
    pass_rate = (pass_count / total * 100.0) if total > 0 else 0.0
    avg_duration = round(sum(durations) / len(durations), 2) if durations else 0.0
    max_duration = round(max(durations), 2) if durations else 0.0
    current_status = str(rows[-1].get("status", "")) if rows else ""
    current_status_streak = 0
    current_failure_streak = 0
    if rows and current_status:
        for r in reversed(rows):
            if str(r.get("status", "")) != current_status:
                break
            current_status_streak += 1
        for r in reversed(rows):
            if str(r.get("status", "")) != "fail":
                break
            current_failure_streak += 1
    slowest_runs = sorted(
        slowest_candidates,
        key=lambda r: (-_safe_float(r.get("duration_seconds")), int(r.get("index", 0) or 0)),
    )[:5]
    return {
        "total_runs": total,
        "pass_count": pass_count,
        "pass_rate": round(pass_rate, 2),
        "avg_duration_seconds": avg_duration,
        "max_duration_seconds": max_duration,
        "current_status": current_status,
        "current_status_streak": current_status_streak,
        "current_failure_streak": current_failure_streak,
        "status_counts": status_counts,
        "severity_counts": severity_counts,
        "label_counts": label_counts,
        "failure_reason_counts": dict(
            sorted(failure_reason_counts.items(), key=lambda x: (-int(x[1]), str(x[0])))
        ),
        "latest_runs": latest_candidates[-5:],
        "slowest_runs": slowest_runs,
        "regressions": regressions[-10:],
    }


def render_history_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("History Trend Report")
    lines.append(f"total_runs: {summary.get('total_runs', 0)}")
    lines.append(f"pass_count: {summary.get('pass_count', 0)}")
    lines.append(f"pass_rate: {summary.get('pass_rate', 0.0)}%")
    lines.append(f"avg_duration_seconds: {float(summary.get('avg_duration_seconds', 0.0) or 0.0):.2f}")
    lines.append(f"max_duration_seconds: {float(summary.get('max_duration_seconds', 0.0) or 0.0):.2f}")
    lines.append(f"current_status: {summary.get('current_status', '')}")
    lines.append(f"current_status_streak: {int(summary.get('current_status_streak', 0) or 0)}")
    lines.append(f"current_failure_streak: {int(summary.get('current_failure_streak', 0) or 0)}")
    lines.append("status_counts:")
    for k, v in dict(summary.get("status_counts", {})).items():
        lines.append(f"  - {k}: {v}")
    lines.append("severity_counts:")
    for k, v in dict(summary.get("severity_counts", {})).items():
        lines.append(f"  - {k}: {v}")
    lines.append("top_labels:")
    labels = dict(summary.get("label_counts", {}))
    if labels:
        for k, v in sorted(labels.items(), key=lambda x: (-x[1], x[0]))[:10]:
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  - (none)")
    lines.append("failure_reason_counts:")
    failure_reasons = dict(summary.get("failure_reason_counts", {}))
    if failure_reasons:
        for k, v in sorted(failure_reasons.items(), key=lambda x: (-int(x[1]), str(x[0])))[:10]:
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  - (none)")
    lines.append("latest_runs:")
    latest = summary.get("latest_runs", [])
    if isinstance(latest, list) and latest:
        for r in latest:
            if isinstance(r, dict):
                lines.append(
                    f"  - idx={r.get('index')} status={r.get('status')} severity={r.get('severity')} duration={float(r.get('duration_seconds', 0.0) or 0.0):.2f}s label={r.get('label')} reason={r.get('reason')} analysis_id={r.get('analysis_id')}"
                )
    else:
        lines.append("  - (none)")
    lines.append("slowest_runs:")
    slow = summary.get("slowest_runs", [])
    if isinstance(slow, list) and slow:
        for r in slow:
            if isinstance(r, dict):
                lines.append(
                    f"  - idx={r.get('index')} duration={float(r.get('duration_seconds', 0.0) or 0.0):.2f}s status={r.get('status')} severity={r.get('severity')} label={r.get('label')} analysis_id={r.get('analysis_id')}"
                )
    else:
        lines.append("  - (none)")
    lines.append("recent_regressions:")
    regs = summary.get("regressions", [])
    if isinstance(regs, list) and regs:
        for r in regs:
            if isinstance(r, dict):
                lines.append(
                    f"  - idx={r.get('index')} {r.get('from')} -> {r.get('to')} reason={r.get('reason')} label={r.get('label')}"
                )
    else:
        lines.append("  - (none)")
    return "\n".join(lines)


def render_history_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# History Trend Report")
    lines.append("")
    lines.append(f"- **Total runs:** {summary.get('total_runs', 0)}")
    lines.append(f"- **Pass count:** {summary.get('pass_count', 0)}")
    lines.append(f"- **Pass rate:** {summary.get('pass_rate', 0.0)}%")
    lines.append(f"- **Average duration seconds:** {float(summary.get('avg_duration_seconds', 0.0) or 0.0):.2f}")
    lines.append(f"- **Max duration seconds:** {float(summary.get('max_duration_seconds', 0.0) or 0.0):.2f}")
    lines.append(f"- **Current status:** {summary.get('current_status', '')}")
    lines.append(f"- **Current status streak:** {int(summary.get('current_status_streak', 0) or 0)}")
    lines.append(f"- **Current failure streak:** {int(summary.get('current_failure_streak', 0) or 0)}")
    lines.append("")
    lines.append("## Status Counts")
    for k, v in dict(summary.get("status_counts", {})).items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")
    lines.append("## Severity Counts")
    for k, v in dict(summary.get("severity_counts", {})).items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")
    lines.append("## Top Labels")
    labels = dict(summary.get("label_counts", {}))
    if labels:
        for k, v in sorted(labels.items(), key=lambda x: (-x[1], x[0]))[:10]:
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Failure Reason Counts")
    failure_reasons = dict(summary.get("failure_reason_counts", {}))
    if failure_reasons:
        for k, v in sorted(failure_reasons.items(), key=lambda x: (-int(x[1]), str(x[0])))[:10]:
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Latest Runs")
    latest = summary.get("latest_runs", [])
    if isinstance(latest, list) and latest:
        for r in latest:
            if isinstance(r, dict):
                lines.append(
                    f"- idx={r.get('index')} status=`{r.get('status')}` severity=`{r.get('severity')}` duration={float(r.get('duration_seconds', 0.0) or 0.0):.2f}s label=`{r.get('label')}` reason=`{r.get('reason')}` analysis_id=`{r.get('analysis_id')}`"
                )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Slowest Runs")
    slow = summary.get("slowest_runs", [])
    if isinstance(slow, list) and slow:
        for r in slow:
            if isinstance(r, dict):
                lines.append(
                    f"- idx={r.get('index')} duration={float(r.get('duration_seconds', 0.0) or 0.0):.2f}s status=`{r.get('status')}` severity=`{r.get('severity')}` label=`{r.get('label')}` analysis_id=`{r.get('analysis_id')}`"
                )
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Recent Regressions")
    regs = summary.get("regressions", [])
    if isinstance(regs, list) and regs:
        for r in regs:
            if isinstance(r, dict):
                lines.append(
                    f"- idx={r.get('index')} `{r.get('from')}` -> `{r.get('to')}` reason=`{r.get('reason')}` label=`{r.get('label')}`"
                )
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def summarize_history_file(path: Path, output: str = "text", label: str = "", last_n: int = 0) -> str:
    rows = filter_history_rows(load_history_rows(path), label=label, last_n=last_n)
    summary = build_history_summary(rows)
    if output == "json":
        return json.dumps(summary, ensure_ascii=False, indent=2)
    if output == "markdown":
        return render_history_summary_markdown(summary)
    return render_history_summary_text(summary)


def should_fail_history(
    *,
    mode: str,
    summary: dict[str, Any],
    min_pass_rate: float,
    max_avg_duration: float = 0.0,
    max_duration: float = 0.0,
) -> bool:
    m = (mode or "").strip().lower()
    if not m:
        return False
    if m == "regression":
        regs = summary.get("regressions", [])
        return isinstance(regs, list) and len(regs) > 0
    if m == "passrate":
        try:
            pr = float(summary.get("pass_rate", 0.0))
        except (TypeError, ValueError):
            pr = 0.0
        return pr < float(min_pass_rate)
    if m == "duration":
        limit = _safe_float(max_avg_duration)
        if limit <= 0:
            return False
        return _safe_float(summary.get("avg_duration_seconds")) > limit
    if m == "max_duration":
        limit = _safe_float(max_duration)
        if limit <= 0:
            return False
        return _safe_float(summary.get("max_duration_seconds")) > limit
    raise ValueError(f"unsupported history fail mode: {mode}")


def history_failure_reasons(
    *,
    mode: str,
    failed: bool,
    summary: dict[str, Any],
    min_pass_rate: float,
    max_avg_duration: float = 0.0,
    max_duration: float = 0.0,
) -> list[str]:
    if not failed:
        return []
    m = (mode or "").strip().lower()
    if m == "regression":
        count = len(summary.get("regressions", [])) if isinstance(summary.get("regressions", []), list) else 0
        return [f"history_regressions:{count}"]
    if m == "passrate":
        return [f"passrate_below:{_safe_float(min_pass_rate):.2f}"]
    if m == "duration":
        return [f"avg_duration_above:{_safe_float(max_avg_duration):.2f}"]
    if m == "max_duration":
        return [f"max_duration_above:{_safe_float(max_duration):.2f}"]
    return [m] if m else []


def build_history_gate_result(
    *,
    history_path: Path,
    mode: str,
    min_pass_rate: float,
    max_avg_duration: float = 0.0,
    max_duration: float = 0.0,
    failed: bool,
    summary: dict[str, Any],
) -> dict[str, Any]:
    token = f"{time.time()}:{history_path}:{mode}:{min_pass_rate}:{max_avg_duration}:{max_duration}:{uuid.uuid4()}"
    analysis_id = hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": "1",
        "analysis_id": analysis_id,
        "scope": "history",
        "gate_mode": mode or "",
        "min_pass_rate": _safe_float(min_pass_rate),
        "max_avg_duration": _safe_float(max_avg_duration),
        "max_duration": _safe_float(max_duration),
        "status": "fail" if failed else "pass",
        "failure_reasons": history_failure_reasons(
            mode=mode,
            failed=failed,
            summary=summary,
            min_pass_rate=min_pass_rate,
            max_avg_duration=max_avg_duration,
            max_duration=max_duration,
        ),
        "total_runs": int(summary.get("total_runs", 0)),
        "pass_rate": _safe_float(summary.get("pass_rate", 0.0)),
        "avg_duration_seconds": _safe_float(summary.get("avg_duration_seconds", 0.0)),
        "max_duration_seconds": _safe_float(summary.get("max_duration_seconds", 0.0)),
        "current_status": str(summary.get("current_status", "")),
        "current_status_streak": int(_safe_float(summary.get("current_status_streak", 0))),
        "current_failure_streak": int(_safe_float(summary.get("current_failure_streak", 0))),
        "failure_reason_counts": summary.get("failure_reason_counts", {})
        if isinstance(summary.get("failure_reason_counts", {}), dict)
        else {},
        "latest_runs": summary.get("latest_runs", []) if isinstance(summary.get("latest_runs", []), list) else [],
        "slowest_runs": summary.get("slowest_runs", []) if isinstance(summary.get("slowest_runs", []), list) else [],
        "regression_count": len(summary.get("regressions", [])) if isinstance(summary.get("regressions", []), list) else 0,
    }
