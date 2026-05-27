from __future__ import annotations

from collections.abc import Sequence

from agent.semantic_retrieval.schemas import CandidateEvidence, CoverageReport, NeedSlot


class CoverageEvaluator:
    def __init__(self, *, weak_threshold: float = 0.48) -> None:
        self.weak_threshold = weak_threshold

    def evaluate(self, slots: Sequence[NeedSlot], selected: Sequence[CandidateEvidence]) -> CoverageReport:
        slot_ids = [slot.slot_id for slot in slots]
        must_have_ids = [slot.slot_id for slot in slots if slot.necessity_level == "must_have"]
        best_by_slot: dict[str, CandidateEvidence] = {}
        for evidence in selected:
            for sid in evidence.matched_slot_ids:
                if sid not in slot_ids:
                    continue
                current = best_by_slot.get(sid)
                if current is None or evidence.final_score > current.final_score:
                    best_by_slot[sid] = evidence
        covered = tuple(sid for sid in slot_ids if sid in best_by_slot)
        missing = tuple(sid for sid in slot_ids if sid not in best_by_slot)
        weak = tuple(
            sid
            for sid, evidence in best_by_slot.items()
            if evidence.final_score < self.weak_threshold
            or (evidence.verification_level == "unknown" and evidence.implementation_value_score < 0.55)
        )
        must_covered = [sid for sid in must_have_ids if sid in best_by_slot and sid not in weak]
        must_missing_or_weak = [sid for sid in must_have_ids if sid not in must_covered]
        return CoverageReport(
            covered_slots=covered,
            missing_slots=missing,
            weak_slots=weak,
            coverage_rate=len(covered) / max(len(slot_ids), 1),
            must_have_coverage_rate=len(must_covered) / max(len(must_have_ids), 1),
            has_missing_must_have=bool(must_missing_or_weak),
        )
