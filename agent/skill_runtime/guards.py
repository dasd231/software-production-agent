from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agent.skill_runtime.schemas import (
    ContractViolation,
    FormatContract,
    GuardReport,
    ReasoningContract,
    SkillBundle,
    TaskContract,
)
from agent.skill_runtime.utils import contains_any, overlap_score, tokenize

_DANGEROUS_SCOPE_TERMS = {
    "deploy": ("部署", "上线", "production", "prod", "kubectl apply"),
    "delete": ("删除", "remove", "rm -rf", "drop table", "truncate"),
    "train": ("训练", "微调", "finetune", "distill", "蒸馏"),
    "secret": ("密码", "secret", "token", "credential", "密钥"),
    "network": ("爬取", "联网", "web", "download", "external api"),
}


def _scope_explicitly_authorized(goal: str, terms: Sequence[str]) -> bool:
    lower = str(goal or "").lower()
    authorized = False
    for term in terms:
        t = str(term or "").lower().strip()
        if not t or t not in lower:
            continue
        idx = lower.find(t)
        window = lower[max(0, idx - 8): idx + len(t) + 8]
        if any(marker in window for marker in ("不", "不要", "禁止", "别", "without", "no ", "not ")):
            return False
        authorized = True
    return authorized

_TYPE_CHECKERS = {
    "str": lambda v: isinstance(v, str),
    "list": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict),
    "bool": lambda v: isinstance(v, bool),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def _loads_output(output: str | Mapping[str, Any], *, allow_markdown_fence: bool) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(output, Mapping):
        return dict(output), None
    text = str(output or "").strip()
    if allow_markdown_fence and text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid_json: {exc}"
    if not isinstance(obj, dict):
        return None, "output_json_must_be_object"
    return obj, None


class TaskHallucinationGuard:
    """Detect whether a plan/output invents scope outside the user contract."""

    def validate(self, contract: TaskContract, candidate: str | Mapping[str, Any] | Sequence[Any]) -> tuple[ContractViolation, ...]:
        text = json.dumps(candidate, ensure_ascii=False) if not isinstance(candidate, str) else candidate
        violations: list[ContractViolation] = []
        allowed_text = " ".join([contract.user_goal, *contract.allowed_scope, *contract.success_criteria])
        score = overlap_score(allowed_text, text)
        candidate_tokens = tokenize(text)
        allowed_tokens = tokenize(allowed_text)
        novel = candidate_tokens - allowed_tokens
        if score < contract.max_scope_drift and len(novel) >= 18:
            violations.append(
                ContractViolation(
                    kind="task",
                    code="SCOPE_DRIFT",
                    message="候选计划/输出与用户任务契约重合度过低，可能扩展了未授权任务。",
                    severity="medium",
                    location="task_scope",
                )
            )
        for code, terms in _DANGEROUS_SCOPE_TERMS.items():
            if contains_any(text, terms) and not _scope_explicitly_authorized(contract.user_goal, terms):
                violations.append(
                    ContractViolation(
                        kind="task",
                        code=f"UNAUTHORIZED_{code.upper()}",
                        message=f"检测到未在用户目标中授权的高风险范围：{code}。",
                        severity="high" if code in {"deploy", "delete", "secret"} else "medium",
                        location="task_scope",
                    )
                )
        for forbidden in contract.out_of_scope:
            if forbidden and forbidden.lower() in text.lower():
                violations.append(
                    ContractViolation(
                        kind="task",
                        code="OUT_OF_SCOPE_MARKER",
                        message=f"输出触碰 out_of_scope 标记：{forbidden}",
                        severity="high",
                        location="task_scope",
                    )
                )
        return tuple(violations)


class FormatHallucinationGuard:
    """Validate machine-facing output against a strict format contract."""

    def validate(self, contract: FormatContract, output: str | Mapping[str, Any]) -> tuple[dict[str, Any] | None, tuple[ContractViolation, ...]]:
        obj, error = _loads_output(output, allow_markdown_fence=contract.allow_markdown_fence)
        if error:
            return None, (
                ContractViolation("format", "INVALID_JSON", f"输出无法解析为 {contract.schema_name}: {error}", "high", "root"),
            )
        assert obj is not None
        violations: list[ContractViolation] = []
        allowed = set(contract.required_fields) | set(contract.optional_fields)
        for field in contract.required_fields:
            if field not in obj:
                violations.append(ContractViolation("format", "MISSING_REQUIRED_FIELD", f"缺少必填字段：{field}", "high", field))
        if not contract.allow_extra_fields:
            for field in obj:
                if field not in allowed:
                    violations.append(ContractViolation("format", "EXTRA_FIELD", f"未声明字段漂移：{field}", "medium", field))
        for field, type_name in contract.field_types.items():
            if field not in obj:
                continue
            checker = _TYPE_CHECKERS.get(type_name)
            if checker and not checker(obj[field]):
                violations.append(
                    ContractViolation("format", "FIELD_TYPE_MISMATCH", f"字段 {field} 应为 {type_name}", "high", field)
                )
        return obj, tuple(violations)


class ReasoningHallucinationGuard:
    """Guard visible reasoning: no hidden CoT, no evidence-free certainty."""

    def validate(
        self,
        contract: ReasoningContract,
        output: str | Mapping[str, Any],
        *,
        known_evidence_ids: Sequence[str] = (),
    ) -> tuple[ContractViolation, ...]:
        obj = output if isinstance(output, Mapping) else None
        text = json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output
        violations: list[ContractViolation] = []
        if not contract.expose_hidden_chain_of_thought and contains_any(text, contract.banned_markers):
            violations.append(
                ContractViolation(
                    "reasoning",
                    "HIDDEN_COT_EXPOSED_OR_REQUESTED",
                    "输出包含思维链/隐藏推理标记，应改为证据绑定的短决策摘要。",
                    "high",
                    "reasoning",
                )
            )
        if obj and "reasoning" in obj and not contract.expose_hidden_chain_of_thought:
            violations.append(
                ContractViolation(
                    "reasoning",
                    "FREEFORM_REASONING_FIELD",
                    "结构化输出不应包含自由思维链 reasoning 字段；请使用 answer/evidence/risks/next_actions。",
                    "high",
                    "reasoning",
                )
            )
        if obj and contract.require_evidence_ids:
            evidence = obj.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                violations.append(ContractViolation("evidence", "MISSING_EVIDENCE", "需要 evidence 列表支撑可见结论。", "medium", "evidence"))
            else:
                known = {str(item) for item in known_evidence_ids if str(item).strip()}
                for idx, item in enumerate(evidence):
                    if not isinstance(item, Mapping):
                        violations.append(ContractViolation("evidence", "BAD_EVIDENCE_ITEM", "evidence 项必须是对象。", "medium", f"evidence[{idx}]"))
                        continue
                    evidence_id = str(item.get("evidence_id", "") or item.get("id", "")).strip()
                    if not evidence_id:
                        violations.append(ContractViolation("evidence", "MISSING_EVIDENCE_ID", "evidence 项缺少 evidence_id。", "medium", f"evidence[{idx}]"))
                    elif known and evidence_id not in known:
                        violations.append(ContractViolation("evidence", "UNKNOWN_EVIDENCE_ID", f"引用了未知 evidence_id：{evidence_id}", "high", f"evidence[{idx}]"))
        if obj and "decision_brief" in obj:
            brief = obj.get("decision_brief")
            if isinstance(brief, list) and len(brief) > contract.max_visible_reasoning_items:
                violations.append(
                    ContractViolation("reasoning", "VISIBLE_REASONING_TOO_LONG", "可见推理摘要过长，应收敛为少量证据绑定要点。", "medium", "decision_brief")
                )
        return tuple(violations)


class ContractGuard:
    def __init__(self) -> None:
        self.task_guard = TaskHallucinationGuard()
        self.format_guard = FormatHallucinationGuard()
        self.reasoning_guard = ReasoningHallucinationGuard()

    def validate(
        self,
        bundle: SkillBundle,
        output: str | Mapping[str, Any],
        *,
        candidate_plan: str | Mapping[str, Any] | Sequence[Any] | None = None,
        known_evidence_ids: Sequence[str] = (),
    ) -> GuardReport:
        violations: list[ContractViolation] = []
        warnings: list[ContractViolation] = []
        plan_or_output = candidate_plan if candidate_plan is not None else output
        violations.extend(self.task_guard.validate(bundle.task_contract, plan_or_output))
        normalized, format_violations = self.format_guard.validate(bundle.format_contract, output)
        violations.extend(format_violations)
        reasoning_target: str | Mapping[str, Any] = normalized if normalized is not None else output
        violations.extend(self.reasoning_guard.validate(bundle.reasoning_contract, reasoning_target, known_evidence_ids=known_evidence_ids))
        selected_ids = tuple(skill.skill_id for skill in bundle.selected_skills)
        if not selected_ids:
            violations.append(ContractViolation("skill", "NO_SKILL_SELECTED", "执行前没有获取 SkillBundle。", "high", "skills"))
        if "skill.task_contract" not in selected_ids:
            warnings.append(ContractViolation("skill", "BASELINE_TASK_SKILL_MISSING", "缺少任务契约 Skill。", "medium", "skills"))
        if "skill.format_contract" not in selected_ids:
            warnings.append(ContractViolation("skill", "BASELINE_FORMAT_SKILL_MISSING", "缺少格式契约 Skill。", "medium", "skills"))
        if "skill.reasoning_brief" not in selected_ids:
            warnings.append(ContractViolation("skill", "BASELINE_REASONING_SKILL_MISSING", "缺少可见推理摘要 Skill。", "medium", "skills"))
        return GuardReport(
            ok=not violations,
            violations=tuple(violations),
            warnings=tuple(warnings),
            selected_skill_ids=selected_ids,
            normalized_output=normalized,
        )
