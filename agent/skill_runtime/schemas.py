from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high", "critical"]
ViolationKind = Literal["task", "format", "reasoning", "skill", "evidence"]


@dataclass(frozen=True, slots=True)
class SkillCard:
    skill_id: str
    name: str
    description: str
    capability_tags: tuple[str, ...]
    task_types: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    output_contract: str = "freeform_summary"
    guardrails: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    risk_level: RiskLevel = "low"
    dependencies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        return data


@dataclass(frozen=True, slots=True)
class TaskContract:
    task_id: str
    user_goal: str
    task_type: str
    allowed_scope: tuple[str, ...]
    out_of_scope: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    required_skill_ids: tuple[str, ...] = ()
    max_scope_drift: float = 0.12

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        return data


@dataclass(frozen=True, slots=True)
class FormatContract:
    schema_name: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    field_types: dict[str, str] = field(default_factory=dict)
    allow_extra_fields: bool = False
    allow_markdown_fence: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_fields"] = list(self.required_fields)
        data["optional_fields"] = list(self.optional_fields)
        return data


@dataclass(frozen=True, slots=True)
class ReasoningContract:
    mode: Literal["answer_only", "evidence_summary", "decision_brief"] = "evidence_summary"
    expose_hidden_chain_of_thought: bool = False
    require_evidence_ids: bool = True
    max_visible_reasoning_items: int = 5
    banned_markers: tuple[str, ...] = (
        "chain of thought",
        "思维链",
        "逐步推理",
        "hidden reasoning",
        "internal monologue",
        "我在脑中",
    )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["banned_markers"] = list(self.banned_markers)
        return data


@dataclass(frozen=True, slots=True)
class ContractViolation:
    kind: ViolationKind
    code: str
    message: str
    severity: RiskLevel = "medium"
    location: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillBundle:
    task_contract: TaskContract
    selected_skills: tuple[SkillCard, ...]
    format_contract: FormatContract
    reasoning_contract: ReasoningContract
    assembly_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "skill_bundle.v1",
            "task_contract": self.task_contract.to_dict(),
            "selected_skills": [skill.to_dict() for skill in self.selected_skills],
            "format_contract": self.format_contract.to_dict(),
            "reasoning_contract": self.reasoning_contract.to_dict(),
            "assembly_notes": list(self.assembly_notes),
        }


@dataclass(frozen=True, slots=True)
class GuardReport:
    ok: bool
    violations: tuple[ContractViolation, ...] = ()
    warnings: tuple[ContractViolation, ...] = ()
    selected_skill_ids: tuple[str, ...] = ()
    normalized_output: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "contract_guard_report.v1",
            "ok": self.ok,
            "violations": [item.to_dict() for item in self.violations],
            "warnings": [item.to_dict() for item in self.warnings],
            "selected_skill_ids": list(self.selected_skill_ids),
            "normalized_output": self.normalized_output or {},
        }
