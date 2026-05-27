from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent.semantic_retrieval.retrievers.base import BaseRetriever, evidence_from_text, lexical_score, merge_evidence
from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot, TaskSemanticFrame


@dataclass(frozen=True, slots=True)
class TextDocument:
    doc_id: str
    title: str
    content: str
    source_type: str = "chunk"
    verification_level: str = "static_verified"
    source_ref: str = "local_corpus://builtin"


_BUILTIN_DOCS: tuple[TextDocument, ...] = (
    TextDocument(
        doc_id="generic_saas_intro",
        title="SaaS 是什么：通用介绍",
        content="SaaS 是 Software as a Service，通常通过浏览器访问，适合多用户在线使用。本文只介绍概念，不包含 tenant_id、权限拦截、缓存隔离或测试实现。",
        verification_level="unknown",
        source_ref="local_corpus://generic_saas_intro",
    ),
    TextDocument(
        doc_id="tenant_query_interceptor_note",
        title="TenantContext 查询拦截实现笔记",
        content="Spring Boot / MyBatis 场景下，将 tenant_id 放入 TenantContext，查询拦截器统一追加 tenant_id 条件；缓存 key 使用 tenant_id:business_key；跨租户管理动作写 OperatorLog。",
        source_type="code_ref",
        verification_level="static_verified",
        source_ref="local_corpus://tenant_query_interceptor_note",
    ),
    TextDocument(
        doc_id="ticket_status_log_note",
        title="TicketStatusLog 与 OperatorLog 实现笔记",
        content="TicketService.changeStatus 在事务中校验 from_status/to_status，更新 ticket.version，插入 TicketStatusLog，并记录 OperatorLog。关闭状态禁止继续处理。",
        source_type="code_ref",
        verification_level="static_verified",
        source_ref="local_corpus://ticket_status_log_note",
    ),
    TextDocument(
        doc_id="seckill_lua_mq_note",
        title="秒杀 Lua 扣减与 MQ 下单笔记",
        content="Redis Lua 脚本同时检查库存和 user_id + activity_id 幂等标记，扣减成功后发送 MQ；消费者用 request_id 幂等落库，失败进入死信并触发库存回滚。",
        source_type="code_ref",
        verification_level="static_verified",
        source_ref="local_corpus://seckill_lua_mq_note",
    ),
    TextDocument(
        doc_id="auth_filter_note",
        title="认证过滤器与白名单实现笔记",
        content="AuthFilter 先匹配白名单，再解析 JWT/Session，校验 Redis token blacklist，注入 AuthContext；权限拦截器根据 RBAC 权限码判断 401/403。密码使用 BCrypt。",
        source_type="code_ref",
        verification_level="static_verified",
        source_ref="local_corpus://auth_filter_note",
    ),
)


class KeywordRetriever(BaseRetriever):
    name = "keyword"

    def __init__(self, documents: Sequence[TextDocument] | None = None, *, min_score: float = 0.05) -> None:
        self.documents = list(documents) if documents is not None else list(_BUILTIN_DOCS)
        self.min_score = min_score

    def retrieve(
        self,
        slots: Sequence[NeedSlot],
        queries_by_slot: Mapping[str, Sequence[str]],
        frame: TaskSemanticFrame | None = None,
    ) -> list[CandidateEvidence]:
        candidates: list[CandidateEvidence] = []
        for doc in self.documents:
            matched: list[str] = []
            best = 0.0
            for slot in slots:
                queries = [slot.name, *slot.query_terms, *queries_by_slot.get(slot.slot_id, ())]
                score = lexical_score(queries, doc.content + "\n" + doc.title)
                if score >= self.min_score:
                    matched.append(slot.slot_id)
                    best = max(best, score)
            if matched:
                candidates.append(
                    evidence_from_text(
                        source_type=doc.source_type,
                        title=doc.title,
                        content=doc.content,
                        matched_slot_ids=matched,
                        raw_similarity_score=best,
                        verification_level=doc.verification_level,
                        source_ref=doc.source_ref,
                        metadata={"retriever": self.name, "doc_id": doc.doc_id},
                    )
                )
        return merge_evidence(candidates)
