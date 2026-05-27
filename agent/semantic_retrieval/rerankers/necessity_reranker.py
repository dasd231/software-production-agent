from __future__ import annotations

from collections.abc import Sequence

from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot, TaskSemanticFrame

_VERIFICATION_SCORE = {
    "human_verified": 1.0,
    "runtime_verified": 0.95,
    "static_verified": 0.85,
    "llm_inferred": 0.55,
    "unknown": 0.35,
}
_STRUCTURE_TERMS = (
    "tenant_id",
    "table",
    "表",
    "index",
    "schema",
    "entity",
    "实体",
    "status",
    "状态",
    "from_status",
    "to_status",
    "api",
    "接口",
    "redis",
    "mq",
    "jwt",
    "session",
    "operatorlog",
    "ticketstatuslog",
)
_IMPLEMENTATION_TERMS = (
    "必须",
    "统一",
    "使用",
    "实现",
    "校验",
    "事务",
    "测试",
    "索引",
    "拦截器",
    "filter",
    "interceptor",
    "redis",
    "lua",
    "mq",
    "rollback",
    "tenant_id",
    "bcryp",
    "blacklist",
)
_GENERIC_TERMS = ("是什么", "简介", "介绍", "concept", "overview", "通常", "适合")


def _clip(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


class NecessityReranker:
    """Rank evidence by task necessity, not by superficial similarity."""

    def rerank(
        self,
        frame: TaskSemanticFrame,
        slots: Sequence[NeedSlot],
        candidates: Sequence[CandidateEvidence],
    ) -> list[CandidateEvidence]:
        slot_by_id = {slot.slot_id: slot for slot in slots}
        must_have = {slot.slot_id for slot in slots if slot.necessity_level == "must_have"}
        for candidate in candidates:
            matched = [slot_by_id[sid] for sid in candidate.matched_slot_ids if sid in slot_by_id]
            level_scores = []
            for slot in matched:
                if slot.necessity_level == "must_have":
                    level_scores.append(1.0)
                elif slot.necessity_level == "important":
                    level_scores.append(0.74)
                else:
                    level_scores.append(0.45)
            candidate.necessity_score = max(level_scores or [0.25])
            candidate.structure_score = self._structure_score(candidate)
            candidate.implementation_value_score = self._implementation_value(candidate)
            candidate.confidence_score = self._confidence(candidate)
            candidate.coverage_gain_score = _clip(len(set(candidate.matched_slot_ids) & must_have) / max(len(must_have), 1) + 0.35)
            slot_match_score = _clip(len(set(candidate.matched_slot_ids)) / max(min(len(slots), 8), 1))
            superficial_penalty = self._superficial_penalty(candidate)
            candidate.final_score = _clip(
                0.25 * candidate.necessity_score
                + 0.20 * slot_match_score
                + 0.15 * candidate.structure_score
                + 0.15 * candidate.implementation_value_score
                + 0.10 * candidate.confidence_score
                + 0.10 * candidate.coverage_gain_score
                + 0.10 * candidate.raw_similarity_score
                - 0.15 * superficial_penalty
            )
        return sorted(candidates, key=lambda item: (item.final_score, item.implementation_value_score, item.confidence_score), reverse=True)

    def _structure_score(self, candidate: CandidateEvidence) -> float:
        text = (candidate.title + "\n" + candidate.content).lower()
        hits = sum(1 for term in _STRUCTURE_TERMS if term in text)
        if candidate.source_type in {"pattern_card", "code_ref", "graph_relation"}:
            hits += 2
        if candidate.metadata.get("pattern_card"):
            card = candidate.metadata["pattern_card"]
            hits += min(len(card.get("required_entities", [])) + len(card.get("required_tables", [])), 6)
        return _clip(hits / 10)

    def _implementation_value(self, candidate: CandidateEvidence) -> float:
        text = (candidate.title + "\n" + candidate.content).lower()
        hits = sum(1 for term in _IMPLEMENTATION_TERMS if term.lower() in text)
        if candidate.metadata.get("pattern_card"):
            card = candidate.metadata["pattern_card"]
            hits += min(len(card.get("implementation_steps", [])) + len(card.get("test_points", [])), 8)
        if candidate.source_type == "code_ref":
            hits += 2
        return _clip(hits / 12)

    def _confidence(self, candidate: CandidateEvidence) -> float:
        base = _VERIFICATION_SCORE.get(candidate.verification_level, 0.35)
        confidence = float(candidate.metadata.get("confidence", 1.0) or 1.0)
        return _clip(base * confidence)

    def _superficial_penalty(self, candidate: CandidateEvidence) -> float:
        text = (candidate.title + "\n" + candidate.content).lower()
        generic_hits = sum(1 for term in _GENERIC_TERMS if term.lower() in text)
        if generic_hits == 0:
            return 0.0
        low_impl = candidate.implementation_value_score < 0.35
        low_structure = candidate.structure_score < 0.35
        return _clip(0.35 * generic_hits + (0.35 if low_impl else 0.0) + (0.25 if low_structure else 0.0))
