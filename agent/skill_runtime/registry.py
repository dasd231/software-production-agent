from __future__ import annotations

from collections.abc import Sequence

from agent.skill_runtime.schemas import SkillCard, SkillBundle, TaskContract, FormatContract, ReasoningContract
from agent.skill_runtime.utils import overlap_score, tokenize, unique


def builtin_skill_cards() -> list[SkillCard]:
    return [
        SkillCard(
            skill_id="skill.task_contract",
            name="任务契约编译",
            description="把用户目标收束为允许范围、禁止范围、成功标准和所需 Skill，防止 Agent 擅自扩任务。",
            capability_tags=("task_contract", "intent", "scope_guard", "anti_task_hallucination"),
            task_types=("planning", "coding", "research", "workflow"),
            required_inputs=("user_goal",),
            output_contract="task_contract.v1",
            guardrails=("不得增加用户没有授权的部署、训练、删除、付费、外部调用任务。", "任何范围扩展必须显式标为建议而非执行项。"),
            evidence_requirements=("user_goal", "explicit_constraints"),
            risk_level="low",
        ),
        SkillCard(
            skill_id="skill.format_contract",
            name="格式契约校验",
            description="把输出限定到 JSON/schema/字段类型，阻断 markdown 混杂、字段漂移和 schema 漏字段。",
            capability_tags=("format_guard", "schema", "json", "anti_format_hallucination"),
            task_types=("planning", "coding", "workflow", "evaluation"),
            required_inputs=("format_contract",),
            output_contract="format_guard_report.v1",
            guardrails=("结构化输出必须能被机器解析。", "不允许未声明字段静默进入执行层。"),
            evidence_requirements=("schema_name", "required_fields"),
            risk_level="low",
        ),
        SkillCard(
            skill_id="skill.reasoning_brief",
            name="可见推理摘要",
            description="禁止输出伪思维链，改为短的、证据绑定的 decision brief。",
            capability_tags=("reasoning_guard", "cot_guard", "evidence_summary", "anti_reasoning_hallucination"),
            task_types=("planning", "research", "workflow", "evaluation"),
            required_inputs=("evidence_ids",),
            output_contract="decision_brief.v1",
            guardrails=("不暴露隐藏思维链。", "只输出可验证的结论、依据、风险和下一步。", "没有证据时必须说缺证据。"),
            evidence_requirements=("evidence_id", "source_ref"),
            risk_level="medium",
        ),
        SkillCard(
            skill_id="skill.semantic_retrieval",
            name="任务必要性检索",
            description="先生成 TaskSemanticFrame 和 NeedSlot，再围绕必要槽位检索，避免相似性灾难。",
            capability_tags=("semantic_retrieval", "need_slot", "rag", "similarity_disaster"),
            task_types=("research", "coding", "workflow"),
            required_inputs=("user_requirement",),
            output_contract="semantic_context_package.v1",
            guardrails=("禁止直接 user query -> topK chunks。", "must_have 缺失必须暴露 missing_slots。"),
            evidence_requirements=("NeedSlot", "CandidateEvidence", "CoverageReport"),
            risk_level="medium",
        ),
        SkillCard(
            skill_id="skill.workflow_contract",
            name="工作流状态图契约",
            description="把任务组织为状态、节点、条件边、checkpoint、人工介入和副作用门禁。",
            capability_tags=("workflow", "langgraph", "state_graph", "checkpoint", "human_interrupt"),
            task_types=("workflow", "agent_runtime", "enterprise"),
            required_inputs=("goal", "risk_nodes"),
            output_contract="enterprise_workflow_contract.v1",
            guardrails=("副作用节点必须有幂等键。", "高风险节点必须有人审或沙盒。"),
            evidence_requirements=("node_contract", "edge_policy", "release_gate"),
            risk_level="medium",
        ),
        SkillCard(
            skill_id="skill.diff_intelligence",
            name="Diff 原生代码协同",
            description="把代码修改作为 PatchProposal/PatchReview/PatchConflict 管理，而不是让 Agent 随意改文件。",
            capability_tags=("diff", "patch", "code_review", "cli", "multi_agent"),
            task_types=("coding", "review"),
            required_inputs=("change_goal", "diff"),
            output_contract="patch_review.v1",
            guardrails=("所有代码变更必须可回滚。", "冲突和测试影响必须显式列出。"),
            evidence_requirements=("file_path", "hunk", "test_impact"),
            risk_level="medium",
        ),
    ]


class SkillRegistry:
    def __init__(self, skills: Sequence[SkillCard] | None = None) -> None:
        self._skills = {skill.skill_id: skill for skill in (skills or builtin_skill_cards())}

    def list_skills(self) -> list[SkillCard]:
        return [self._skills[key] for key in sorted(self._skills)]

    def get(self, skill_id: str) -> SkillCard | None:
        return self._skills.get(skill_id)

    def select(self, contract: TaskContract, *, max_skills: int = 5) -> list[SkillCard]:
        required = [self._skills[sid] for sid in contract.required_skill_ids if sid in self._skills]
        required_ids = {skill.skill_id for skill in required}
        query = " ".join([contract.user_goal, contract.task_type, *contract.allowed_scope, *contract.success_criteria])
        scored: list[tuple[float, SkillCard]] = []
        for skill in self._skills.values():
            if skill.skill_id in required_ids:
                continue
            skill_text = " ".join([skill.name, skill.description, *skill.capability_tags, *skill.task_types, *skill.guardrails])
            score = overlap_score(query, skill_text)
            if contract.task_type in skill.task_types:
                score += 0.25
            if set(tokenize(query)) & set(skill.capability_tags):
                score += 0.25
            if score > 0:
                scored.append((score, skill))
        selected = [*required]
        for _, skill in sorted(scored, key=lambda item: item[0], reverse=True):
            if len(selected) >= max_skills:
                break
            selected.append(skill)
        # These three are the baseline anti-hallucination skills. They should be
        # present even when the selector has few lexical matches.
        for baseline in ("skill.task_contract", "skill.format_contract", "skill.reasoning_brief"):
            if len(selected) >= max_skills and baseline not in {s.skill_id for s in selected}:
                continue
            skill = self._skills.get(baseline)
            if skill and skill.skill_id not in {s.skill_id for s in selected}:
                selected.append(skill)
        return selected[:max_skills]


def infer_task_type(user_goal: str) -> str:
    text = user_goal.lower()
    if any(term in text for term in ("代码", "开发", "实现", "diff", "patch", "修复")):
        return "coding"
    if any(term in text for term in ("workflow", "langgraph", "工作流", "agent")):
        return "workflow"
    if any(term in text for term in ("检索", "rag", "知识", "文献", "搜索")):
        return "research"
    if any(term in text for term in ("评估", "指标", "测试", "质量")):
        return "evaluation"
    return "planning"


def compile_task_contract(
    user_goal: str,
    *,
    task_id: str = "task",
    explicit_scope: Sequence[str] = (),
    out_of_scope: Sequence[str] = (),
    required_skill_ids: Sequence[str] = (),
) -> TaskContract:
    task_type = infer_task_type(user_goal)
    tokens = sorted(tokenize(user_goal))[:24]
    allowed_scope = unique([*explicit_scope, *tokens])
    default_out = (
        "delete_files_without_confirmation",
        "deploy_to_production_without_confirmation",
        "train_or_call_paid_models_without_confirmation",
        "change_credentials_or_secrets_without_confirmation",
        "invent_external_evidence",
    )
    criteria = (
        "stay_within_user_goal",
        "use_selected_skills_before_execution",
        "produce_schema_valid_output",
        "cite_evidence_or_mark_unknown",
    )
    return TaskContract(
        task_id=task_id,
        user_goal=user_goal,
        task_type=task_type,
        allowed_scope=allowed_scope,
        out_of_scope=unique([*default_out, *out_of_scope]),
        success_criteria=criteria,
        required_skill_ids=unique(required_skill_ids),
    )


def assemble_skill_bundle(
    user_goal: str,
    *,
    task_id: str = "task",
    format_contract: FormatContract | None = None,
    reasoning_contract: ReasoningContract | None = None,
    registry: SkillRegistry | None = None,
    explicit_scope: Sequence[str] = (),
    required_skill_ids: Sequence[str] = (),
) -> SkillBundle:
    reg = registry or SkillRegistry()
    contract = compile_task_contract(
        user_goal,
        task_id=task_id,
        explicit_scope=explicit_scope,
        required_skill_ids=required_skill_ids,
    )
    selected = reg.select(contract)
    fmt = format_contract or FormatContract(
        schema_name="guarded_agent_response.v1",
        required_fields=("answer", "evidence", "risks", "next_actions"),
        optional_fields=("skill_ids", "confidence"),
        field_types={"answer": "str", "evidence": "list", "risks": "list", "next_actions": "list"},
        allow_extra_fields=False,
    )
    reasoning = reasoning_contract or ReasoningContract()
    notes = (
        "Acquire SkillBundle before prompt assembly or action execution.",
        "Task/format/reasoning guards are contracts, not soft prompt suggestions.",
    )
    return SkillBundle(contract, tuple(selected), fmt, reasoning, notes)
