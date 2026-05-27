from __future__ import annotations

from agent.semantic_retrieval.schemas import NeedSlot, TaskSemanticFrame


_TECH_TERMS = {
    "java": ["Spring Boot", "MyBatis", "JPA", "Controller", "Service", "Repository"],
    "spring boot": ["Spring Security", "Interceptor", "Filter", "Controller", "Transactional"],
    "mysql": ["table", "index", "transaction", "optimistic lock", "unique constraint"],
    "redis": ["cache key", "distributed lock", "token bucket", "session cache"],
    "rabbitmq": ["message queue", "dead letter", "retry", "async consumer"],
    "kafka": ["message queue", "consumer group", "event", "async order"],
}


class QueryExpander:
    def expand(self, slot: NeedSlot, frame: TaskSemanticFrame, tech_stack: tuple[str, ...] = ()) -> list[str]:
        terms = [slot.name, slot.description, *slot.query_terms, frame.target_module, frame.domain, *frame.entities]
        tech_terms: list[str] = []
        for tech in tech_stack:
            tech_lower = tech.lower()
            tech_terms.append(tech)
            for key, values in _TECH_TERMS.items():
                if key in tech_lower:
                    tech_terms.extend(values)
        queries = []
        for term in terms:
            if not str(term).strip():
                continue
            queries.append(str(term).strip())
            for tech_term in tech_terms[:8]:
                queries.append(f"{term} {tech_term}".strip())
        return list(dict.fromkeys(queries))[:24]

    def expand_all(self, slots: list[NeedSlot], frame: TaskSemanticFrame, tech_stack: tuple[str, ...] = ()) -> dict[str, list[str]]:
        return {slot.slot_id: self.expand(slot, frame, tech_stack) for slot in slots}
