"""Teacher and task catalogs for project-model distillation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeacherModelSpec:
    id: str
    label: str
    provider: str
    model: str
    role: str
    strengths: tuple[str, ...]
    context_window: int
    cost_tier: str
    availability: str
    usage_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "teacher_model_spec.v1",
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "strengths": list(self.strengths),
            "context_window": self.context_window,
            "cost_tier": self.cost_tier,
            "availability": self.availability,
            "usage_policy": self.usage_policy,
        }


@dataclass(frozen=True)
class TeacherTaskSpec:
    id: str
    label: str
    capability: str
    prompt_contract: str
    expected_output: str
    requires_evidence: bool
    quality_checks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "teacher_task_spec.v1",
            "id": self.id,
            "label": self.label,
            "capability": self.capability,
            "prompt_contract": self.prompt_contract,
            "expected_output": self.expected_output,
            "requires_evidence": self.requires_evidence,
            "quality_checks": list(self.quality_checks),
        }


_TEACHERS: tuple[TeacherModelSpec, ...] = (
    TeacherModelSpec(
        id="openai_reasoning_teacher",
        label="OpenAI reasoning teacher",
        provider="openai",
        model="gpt-4.1",
        role="reasoning_teacher",
        strengths=("architecture_summary", "change_impact_reasoning", "repo_grounded_qa"),
        context_window=128000,
        cost_tier="high",
        availability="configured_when_api_key_present",
        usage_policy="operator_selected_remote_teacher",
    ),
    TeacherModelSpec(
        id="deepseek_reasoning_teacher",
        label="DeepSeek reasoning teacher",
        provider="deepseek",
        model="deepseek-reasoner",
        role="reasoning_teacher",
        strengths=("repo_grounded_qa", "issue_to_code_localization", "architecture_summary"),
        context_window=64000,
        cost_tier="medium",
        availability="configured_when_api_key_present",
        usage_policy="operator_selected_remote_teacher",
    ),
    TeacherModelSpec(
        id="local_main_teacher",
        label="Local main teacher",
        provider="main_deepseek",
        model="deepseek-v4-pro",
        role="local_teacher",
        strengths=("repo_grounded_qa", "symbol_grounding", "action_protocol_sft"),
        context_window=32768,
        cost_tier="low",
        availability="local_runtime_probe_required",
        usage_policy="preferred_for_private_or_low_cost_runs",
    ),
)


_TASKS: tuple[TeacherTaskSpec, ...] = (
    TeacherTaskSpec(
        id="teacher_repo_grounded_qa",
        label="Repository-grounded QA",
        capability="answer project questions from supplied evidence",
        prompt_contract="question + evidence bundle -> answer with citations only",
        expected_output="concise answer plus exact evidence references",
        requires_evidence=True,
        quality_checks=("citation_present", "answer_supported_by_evidence", "no_unsupported_claims"),
    ),
    TeacherTaskSpec(
        id="teacher_architecture_summary",
        label="Architecture summary",
        capability="compress repository structure into faithful explanation",
        prompt_contract="project map + docs + evidence -> architecture summary",
        expected_output="faithful project summary with boundaries and entrypoints",
        requires_evidence=True,
        quality_checks=("coverage", "faithfulness", "citation_present"),
    ),
    TeacherTaskSpec(
        id="teacher_symbol_localization",
        label="Symbol localization",
        capability="resolve symbol to definition and rationale",
        prompt_contract="symbol query + symbol index + evidence -> path and line answer",
        expected_output="definition path, line and short rationale",
        requires_evidence=True,
        quality_checks=("path_match", "line_match", "citation_present"),
    ),
    TeacherTaskSpec(
        id="teacher_issue_to_code",
        label="Issue-to-code localization",
        capability="map natural-language issue to likely files and symbols",
        prompt_contract="issue + repo memory -> ranked files with reasons",
        expected_output="ranked localization answer",
        requires_evidence=True,
        quality_checks=("ranked_files_present", "evidence_present", "unsupported_claims_absent"),
    ),
    TeacherTaskSpec(
        id="teacher_change_impact",
        label="Change impact reasoning",
        capability="predict impacted modules and tests",
        prompt_contract="change request + repo graph + tests -> impact explanation",
        expected_output="affected modules, tests and justification",
        requires_evidence=True,
        quality_checks=("impact_set_present", "test_coverage_present", "evidence_present"),
    ),
)


def list_teacher_models() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _TEACHERS]


def list_teacher_tasks() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _TASKS]
