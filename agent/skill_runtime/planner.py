from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agent.skill_runtime.guards import ContractGuard
from agent.skill_runtime.registry import assemble_skill_bundle
from agent.skill_runtime.schemas import FormatContract, ReasoningContract


def build_skill_runtime_plan(
    goal: str,
    *,
    required_skill_ids: Sequence[str] = (),
    explicit_scope: Sequence[str] = (),
    output_schema_name: str = "guarded_agent_response.v1",
    sample_output: Mapping[str, Any] | str | None = None,
    known_evidence_ids: Sequence[str] = (),
) -> dict[str, Any]:
    format_contract = FormatContract(
        schema_name=output_schema_name or "guarded_agent_response.v1",
        required_fields=("answer", "evidence", "risks", "next_actions"),
        optional_fields=("skill_ids", "confidence", "decision_brief"),
        field_types={"answer": "str", "evidence": "list", "risks": "list", "next_actions": "list"},
        allow_extra_fields=False,
    )
    reasoning_contract = ReasoningContract(mode="evidence_summary", expose_hidden_chain_of_thought=False)
    bundle = assemble_skill_bundle(
        goal,
        task_id="skill_runtime_plan",
        format_contract=format_contract,
        reasoning_contract=reasoning_contract,
        explicit_scope=explicit_scope,
        required_skill_ids=required_skill_ids,
    )
    validation = None
    if sample_output is not None:
        validation = ContractGuard().validate(bundle, sample_output, known_evidence_ids=known_evidence_ids).to_dict()
    return {
        "schema": "skill_runtime_plan.v1",
        "goal": goal,
        "positioning": "Acquire skills first; prompts are assembled from task/format/reasoning contracts rather than free-form layered prompt fragments.",
        "bundle": bundle.to_dict(),
        "anti_hallucination_controls": {
            "task_hallucination": [
                "compile user goal into TaskContract before planning",
                "block unauthorized deploy/delete/train/secret/network scope",
                "mark scope expansion as suggestion, never as execution",
            ],
            "format_hallucination": [
                "validate machine-facing output with FormatContract",
                "reject missing required fields, extra fields, wrong field types, invalid JSON",
                "keep schema version visible for downstream consumers",
            ],
            "reasoning_hallucination": [
                "never expose hidden chain-of-thought",
                "replace free-form reasoning with evidence-bound decision brief",
                "unknown evidence ids or missing evidence become guard violations",
            ],
        },
        "prompt_assembly_rule": [
            "1. select SkillBundle",
            "2. render only selected Skill guardrails",
            "3. attach task contract and format contract",
            "4. require evidence ids for claims",
            "5. validate output before execution or persistence",
        ],
        "validation": validation or {},
    }
