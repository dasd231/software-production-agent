from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from agent.workflow.optimizer import WorkflowOptimizer
from agent.workflow.schema import WorkflowPolicy, WorkflowTraceEvent


@dataclass(slots=True)
class InterviewReadinessReport:
    trace_count: int
    route_keys: dict[str, int]
    route_choices: dict[str, dict[str, int]]
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    talking_points: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = ["# Adaptive Workflow Interview Readiness", ""]
        lines.append(f"- trace_count: `{self.trace_count}`")
        lines.append("- route_keys:")
        for key, count in sorted(self.route_keys.items()):
            lines.append(f"  - `{key}`: {count}")
        lines.append("")
        lines.append("## Strengths")
        lines.extend(f"- {x}" for x in self.strengths)
        lines.append("")
        lines.append("## Gaps / honest limits")
        lines.extend(f"- {x}" for x in self.gaps)
        lines.append("")
        lines.append("## Interview talking points")
        lines.extend(f"- {x}" for x in self.talking_points)
        lines.append("")
        lines.append("## Next steps")
        lines.extend(f"- {x}" for x in self.next_steps)
        return "\n".join(lines) + "\n"


def build_interview_readiness_report(
    events: Iterable[WorkflowTraceEvent],
    *,
    base_policy: WorkflowPolicy,
) -> InterviewReadinessReport:
    rows = list(events)
    route_key_counter: Counter[str] = Counter()
    route_choice_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for event in rows:
        if not event.route_key:
            continue
        route_key_counter[event.route_key] += 1
        if event.route_choice:
            route_choice_counter[event.route_key][event.route_choice] += 1

    opt_report = WorkflowOptimizer(min_samples_per_route=1).analyze(rows, base_policy)
    strengths = [
        "主项目已经有 agent.workflow 状态图运行时，而不是外部玩具 demo。",
        "workflow trace 能从真实 .agent_events.jsonl 转换而来，说明优化闭环接入主链路观测数据。",
        "现有 agent.decision 的 bandit/reward/trace 被复用，单步动作智能与多步图路由智能分层清晰。",
        "支持 checkpoint/resume/human gate/policy versioning，贴近 LangGraph persistence 与 interrupt 思想。",
    ]
    gaps: list[str] = []
    if not rows:
        gaps.append("还没有真实运行 trace，面试演示前应至少跑一次 --demo --events 生成 .agent_events.jsonl。")
    if "execution_strategy" not in route_key_counter:
        gaps.append("真实 trace 中尚未覆盖 execution_strategy 分支，需要更多 workflow demo 或主链路迁移。")
    if "decision_action" not in route_key_counter:
        gaps.append("真实 agent_loop 事件尚未形成足够 decision_action 样本，优化建议统计置信度有限。")
    if not opt_report.findings:
        gaps.append("当前样本量还小，优化器报告更多是框架验证，不应夸大为成熟 RL 系统。")

    talking_points = [
        "我没有直接把 LangGraph 当黑盒接进来，而是抽出 StateGraph、conditional edge、checkpoint、interrupt、trace、optimizer 这些关键机制。",
        "二改重点是 optimization plane：图负责执行，trace 负责观测，reward 负责评分，policy store 负责版本化发布与回滚。",
        "小模型适合学习 route policy / 风险 gate / cache hit 判断，大模型只处理高价值推理节点。",
        "现有 agent_loop 暂时稳定保留，新 workflow runtime 先旁挂接入，再逐步迁移 plan/context/decide/execute。",
    ]
    next_steps = [
        "把 agent.core.agent_loop 的 plan/context/decide/execute/reward 逐步迁移为 workflow node。",
        "把 workflow_events 与 .agent_events 合并 schema，支持同一条 run 的全链路回放。",
        "做 policy canary：新 route_weights 只影响一小部分 run，失败可回滚。",
        "接入 K8s AgentTask：一个 AgentTask 对应一个 workflow run，trace sidecar 收集优化数据。",
    ]
    return InterviewReadinessReport(
        trace_count=len(rows),
        route_keys=dict(route_key_counter),
        route_choices={key: dict(value) for key, value in route_choice_counter.items()},
        strengths=strengths,
        gaps=gaps or ["当前核心闭环已具备；主要差距是更多真实样本与更深 agent_loop 迁移。"],
        talking_points=talking_points,
        next_steps=next_steps,
    )
