from __future__ import annotations

from collections.abc import Sequence

from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot


class DiversityReranker:
    """Select evidence by slot coverage and source diversity."""

    def select(self, ranked: Sequence[CandidateEvidence], slots: Sequence[NeedSlot], max_items: int = 20) -> list[CandidateEvidence]:
        max_items = max(1, int(max_items or 20))
        selected: list[CandidateEvidence] = []
        selected_ids: set[str] = set()
        slot_pick_count: dict[str, int] = {}
        slot_by_id = {slot.slot_id: slot for slot in slots}

        def add(candidate: CandidateEvidence) -> bool:
            if len(selected) >= max_items or candidate.evidence_id in selected_ids:
                return False
            selected.append(candidate)
            selected_ids.add(candidate.evidence_id)
            for sid in candidate.matched_slot_ids:
                slot_pick_count[sid] = slot_pick_count.get(sid, 0) + 1
            return True

        # First pass: every must-have slot gets at least one best evidence.
        for slot in [s for s in slots if s.necessity_level == "must_have"]:
            if len(selected) >= max_items:
                break
            if slot_pick_count.get(slot.slot_id, 0) > 0:
                continue
            for candidate in ranked:
                if slot.slot_id in candidate.matched_slot_ids:
                    add(candidate)
                    break

        # Second pass: important slots get coverage if budget remains.
        for slot in [s for s in slots if s.necessity_level == "important"]:
            if len(selected) >= max_items:
                break
            if slot_pick_count.get(slot.slot_id, 0) > 0:
                continue
            for candidate in ranked:
                if slot.slot_id in candidate.matched_slot_ids:
                    add(candidate)
                    break

        # Third pass: fill high-value evidence without letting one slot dominate.
        source_counts: dict[str, int] = {}
        for candidate in selected:
            source_counts[candidate.source_type] = source_counts.get(candidate.source_type, 0) + 1
        for candidate in ranked:
            if len(selected) >= max_items:
                break
            if candidate.evidence_id in selected_ids:
                continue
            if all(slot_pick_count.get(sid, 0) >= 3 for sid in candidate.matched_slot_ids if sid in slot_by_id):
                continue
            # Prefer not to fill the whole context with one source type, but do
            # not block if there is still plenty of budget.
            if source_counts.get(candidate.source_type, 0) >= max(3, max_items // 2) and len(selected) < max_items - 2:
                continue
            if add(candidate):
                source_counts[candidate.source_type] = source_counts.get(candidate.source_type, 0) + 1
        return selected
