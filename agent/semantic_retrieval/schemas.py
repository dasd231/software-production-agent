from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SlotType = Literal[
    "entity_model",
    "architecture_pattern",
    "permission_rule",
    "data_constraint",
    "workflow_rule",
    "risk_case",
    "test_point",
    "code_reference",
    "error_memory",
    "api_design",
    "database_design",
    "security_constraint",
]
NecessityLevel = Literal["must_have", "important", "optional"]
EvidenceType = Literal[
    "PatternCard",
    "ModuleCard",
    "CodeRef",
    "Chunk",
    "SymbolRef",
    "GraphRelation",
    "ErrorMemoryCard",
    "TestPoint",
]
SourceType = Literal[
    "chunk",
    "pattern_card",
    "module_card",
    "code_ref",
    "symbol_ref",
    "graph_relation",
    "error_memory",
    "test_case",
]
VerificationLevel = Literal["static_verified", "runtime_verified", "human_verified", "llm_inferred", "unknown"]


@dataclass(frozen=True, slots=True)
class SemanticRetrievalRequest:
    task_id: str
    user_requirement: str
    project_type: str = ""
    tech_stack: tuple[str, ...] = ()
    existing_project_summary: str = ""
    max_context_items: int = 20

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticRetrievalRequest":
        return cls(
            task_id=str(data.get("task_id", "task") or "task"),
            user_requirement=str(data.get("user_requirement", "") or ""),
            project_type=str(data.get("project_type", "") or ""),
            tech_stack=tuple(str(item) for item in data.get("tech_stack", []) if str(item))
            if isinstance(data.get("tech_stack"), list)
            else (),
            existing_project_summary=str(data.get("existing_project_summary", "") or ""),
            max_context_items=max(int(data.get("max_context_items", 20) or 20), 1),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tech_stack"] = list(self.tech_stack)
        return data


@dataclass(frozen=True, slots=True)
class TaskSemanticFrame:
    raw_requirement: str
    task_type: str
    domain: str
    product_type: str
    target_module: str
    entities: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    likely_patterns: tuple[str, ...] = ()
    risk_points: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "entities",
            "relations",
            "constraints",
            "required_capabilities",
            "likely_patterns",
            "risk_points",
        ):
            data[key] = list(data[key])
        return data


@dataclass(frozen=True, slots=True)
class NeedSlot:
    slot_id: str
    slot_type: SlotType
    name: str
    description: str
    necessity_level: NecessityLevel
    expected_evidence_types: tuple[EvidenceType, ...] = ()
    query_terms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["expected_evidence_types"] = list(self.expected_evidence_types)
        data["query_terms"] = list(self.query_terms)
        return data


@dataclass(frozen=True, slots=True)
class PatternCard:
    pattern_id: str
    name: str
    category: str
    applicable_scenarios: tuple[str, ...]
    problem: str
    solution: str
    required_entities: tuple[str, ...] = ()
    required_modules: tuple[str, ...] = ()
    required_tables: tuple[str, ...] = ()
    required_interfaces: tuple[str, ...] = ()
    implementation_steps: tuple[str, ...] = ()
    common_pitfalls: tuple[str, ...] = ()
    test_points: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    confidence: float = 0.8
    verification_level: VerificationLevel = "human_verified"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, tuple):
                data[key] = list(value)
        return data


@dataclass(slots=True)
class CandidateEvidence:
    evidence_id: str
    source_type: SourceType
    title: str
    content: str
    matched_slot_ids: tuple[str, ...] = ()
    raw_similarity_score: float = 0.0
    necessity_score: float = 0.0
    structure_score: float = 0.0
    implementation_value_score: float = 0.0
    confidence_score: float = 0.0
    coverage_gain_score: float = 0.0
    final_score: float = 0.0
    verification_level: VerificationLevel = "unknown"
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["matched_slot_ids"] = list(self.matched_slot_ids)
        return data


@dataclass(frozen=True, slots=True)
class CoverageReport:
    covered_slots: tuple[str, ...]
    missing_slots: tuple[str, ...]
    weak_slots: tuple[str, ...]
    coverage_rate: float
    must_have_coverage_rate: float
    has_missing_must_have: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("covered_slots", "missing_slots", "weak_slots"):
            data[key] = list(data[key])
        return data


@dataclass(frozen=True, slots=True)
class SemanticContextPackage:
    task_summary: str
    task_frame: TaskSemanticFrame
    need_slots: tuple[NeedSlot, ...]
    selected_patterns: tuple[dict[str, Any], ...] = ()
    selected_modules: tuple[dict[str, Any], ...] = ()
    selected_code_refs: tuple[dict[str, Any], ...] = ()
    selected_error_memories: tuple[dict[str, Any], ...] = ()
    constraints: tuple[str, ...] = ()
    risk_warnings: tuple[str, ...] = ()
    implementation_suggestions: tuple[str, ...] = ()
    test_suggestions: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    coverage_report: CoverageReport | None = None
    selected_evidence: tuple[CandidateEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "semantic_context_package.v1",
            "task_summary": self.task_summary,
            "task_frame": self.task_frame.to_dict(),
            "need_slots": [slot.to_dict() for slot in self.need_slots],
            "selected_patterns": list(self.selected_patterns),
            "selected_modules": list(self.selected_modules),
            "selected_code_refs": list(self.selected_code_refs),
            "selected_error_memories": list(self.selected_error_memories),
            "constraints": list(self.constraints),
            "risk_warnings": list(self.risk_warnings),
            "implementation_suggestions": list(self.implementation_suggestions),
            "test_suggestions": list(self.test_suggestions),
            "missing_slots": list(self.missing_slots),
            "coverage_report": self.coverage_report.to_dict() if self.coverage_report else {},
            "selected_evidence": [evidence.to_dict() for evidence in self.selected_evidence],
        }
