from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent.semantic_retrieval.schemas import CandidateEvidence, CoverageReport, NeedSlot, SemanticContextPackage, TaskSemanticFrame


def _unique(items: Sequence[str] | list[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _slot_name_by_id(slots: Sequence[NeedSlot]) -> dict[str, str]:
    return {slot.slot_id: slot.name for slot in slots}


class ContextPackageBuilder:
    """Compress selected evidence into a structured context package."""

    def build(
        self,
        frame: TaskSemanticFrame,
        slots: Sequence[NeedSlot],
        selected: Sequence[CandidateEvidence],
        coverage: CoverageReport,
    ) -> SemanticContextPackage:
        selected_patterns: list[dict[str, Any]] = []
        selected_modules: list[dict[str, Any]] = []
        selected_code_refs: list[dict[str, Any]] = []
        selected_error_memories: list[dict[str, Any]] = []
        constraints: list[str] = list(frame.constraints)
        risk_warnings: list[str] = list(frame.risk_points)
        implementation_suggestions: list[str] = []
        test_suggestions: list[str] = []

        for evidence in selected:
            card = evidence.metadata.get("pattern_card")
            matched_slot_names = [slot.name for slot in slots if slot.slot_id in evidence.matched_slot_ids]
            if card:
                selected_patterns.append(
                    {
                        "pattern_id": card.get("pattern_id"),
                        "name": card.get("name"),
                        "category": card.get("category"),
                        "reason": card.get("problem"),
                        "matched_slots": matched_slot_names,
                        "implementation_points": list(card.get("implementation_steps", [])),
                        "common_pitfalls": list(card.get("common_pitfalls", [])),
                        "test_points": list(card.get("test_points", [])),
                        "verification_level": evidence.verification_level,
                        "source_ref": evidence.source_ref,
                        "score": round(evidence.final_score, 4),
                    }
                )
                constraints.extend(str(step) for step in card.get("solution", "").split("；") if str(step).strip())
                implementation_suggestions.extend(card.get("implementation_steps", []))
                risk_warnings.extend(card.get("common_pitfalls", []))
                test_suggestions.extend(card.get("test_points", []))
            elif evidence.source_type in {"code_ref", "symbol_ref"}:
                selected_code_refs.append(
                    {
                        "title": evidence.title,
                        "matched_slots": matched_slot_names,
                        "content": evidence.content,
                        "verification_level": evidence.verification_level,
                        "source_ref": evidence.source_ref,
                        "score": round(evidence.final_score, 4),
                    }
                )
                implementation_suggestions.append(evidence.content)
            elif evidence.source_type == "module_card":
                selected_modules.append(evidence.to_dict())
            elif evidence.source_type == "error_memory":
                selected_error_memories.append(evidence.to_dict())
                risk_warnings.append(evidence.content)
            else:
                # Generic chunks are allowed as weak context, but only after the
                # package has been structured by patterns/code refs.
                if evidence.implementation_value_score >= 0.5:
                    implementation_suggestions.append(evidence.content)

        slot_names = _slot_name_by_id(slots)
        missing_slot_names = tuple(slot_names.get(sid, sid) for sid in coverage.missing_slots)
        if coverage.weak_slots:
            risk_warnings.extend(f"槽位证据较弱，需要人工复核：{slot_names.get(sid, sid)}" for sid in coverage.weak_slots)
        if coverage.has_missing_must_have:
            risk_warnings.append("存在 must_have 槽位缺失或证据较弱，不能直接进入无人值守代码生成。")

        return SemanticContextPackage(
            task_summary=self._summary(frame),
            task_frame=frame,
            need_slots=tuple(slots),
            selected_patterns=tuple(selected_patterns),
            selected_modules=tuple(selected_modules),
            selected_code_refs=tuple(selected_code_refs),
            selected_error_memories=tuple(selected_error_memories),
            constraints=_unique(constraints),
            risk_warnings=_unique(risk_warnings),
            implementation_suggestions=_unique(implementation_suggestions),
            test_suggestions=_unique(test_suggestions),
            missing_slots=missing_slot_names,
            coverage_report=coverage,
            selected_evidence=tuple(selected),
        )

    def _summary(self, frame: TaskSemanticFrame) -> str:
        module = frame.target_module.replace("_", " ")
        domain = frame.domain.replace("_", " ")
        return f"用户任务被解析为 {domain} 领域的 {module} 软件生产任务；上下文按任务必要性槽位组织，而非按原始 query 相似度堆叠。"
