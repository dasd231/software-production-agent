"""RAG retrieval QA.

函数流程图：
    answer_question(question, vector_index, cards, research=...)
      -> retrieve_evidence_unified()  # baseline 或 ResearchRAGConfig（多查询 RRF / CE / LIM）
      -> _select_relevant_cards()
      -> 可选 web_results
      -> 抽取式 或 LLM 生成式（带 [E]/[C] 引用）
      -> 可选基于置信度的 abstain
      -> dict：answer / evidence / confidence / retrieval / trace

研究向扩展见 `rag_pipeline.ResearchRAGConfig` 与 `benchmark_research_config()`。
"""

from __future__ import annotations

from typing import Any

from agent.learning.rag_eval import aggregate_answer_metrics
from agent.learning.rag_pipeline import ResearchRAGConfig, retrieve_evidence_unified
from agent.learning.schemas import KnowledgeCard, VectorRecord
from agent.learning.vector_store import VectorIndex
from agent.llm.providers import create_openai_compatible_client, resolve_llm_provider


def _select_relevant_cards(question: str, cards: list[KnowledgeCard], limit: int = 3) -> list[KnowledgeCard]:
    q = question.lower()
    scored: list[tuple[int, KnowledgeCard]] = []
    for card in cards:
        haystack = " ".join([card.title, card.summary, " ".join(card.tags), " ".join(card.questions)]).lower()
        score = sum(1 for token in q.split() if token and token in haystack)
        if score:
            scored.append((score, card))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [card for _, card in scored[:limit]]


def _minmax_scores(evidence: list[tuple[float, VectorRecord]]) -> list[tuple[float, VectorRecord]]:
    if not evidence:
        return evidence
    scores = [float(s) for s, _ in evidence]
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [(1.0, r) for _, r in evidence]
    return [((float(s) - lo) / (hi - lo), r) for s, r in evidence]


def _calculate_confidence(
    evidence: list[tuple[float, VectorRecord]],
    relevant_cards: list[KnowledgeCard],
    *,
    total_cards: int,
) -> float:
    if not evidence:
        return 0.0
    scores = [float(s) for s, _ in evidence]
    top = scores[0]
    separation = (top - scores[1]) / top if len(scores) > 1 and top > 1e-12 else 0.5
    separation = max(0.0, min(separation, 1.0))
    strength = min(top * 15.0, 1.0) if top < 0.15 else min(top, 1.0)
    density = min(len(evidence) / 5.0, 1.0)
    pool = max(1, min(max(total_cards, 1), 15))
    card_cov = min(len(relevant_cards) / pool, 1.0)
    return min(0.3 * strength + 0.25 * separation + 0.2 * density + 0.25 * card_cov, 1.0)


def _web_blocks(web_results: list[dict[str, Any]] | None, limit: int = 5) -> str:
    if not web_results:
        return ""
    parts: list[str] = []
    for i, w in enumerate(web_results[:limit], 1):
        title = str(w.get("title", "") or "")[:120]
        url = str(w.get("url", "") or "")
        snippet = str(w.get("snippet", "") or "")[:400]
        parts.append(f"[W{i}] {title}\n{url}\n{snippet}")
    return "\n\n".join(parts)


def _build_extractive_answer(
    relevant_cards: list[KnowledgeCard],
    evidence: list[tuple[float, VectorRecord]],
    *,
    web_results: list[dict[str, Any]] | None,
) -> str:
    card_lines = [f"- {card.title}: {card.summary[:220]}" for card in relevant_cards]
    evidence_lines = [
        f"- {record.metadata.get('path', '')}:{record.metadata.get('start_line')}-{record.metadata.get('end_line')} score={score:.6f}"
        for score, record in evidence
    ]
    out = "基于当前本地索引，相关知识卡如下：\n" + "\n".join(card_lines or ["- 未命中知识卡"])
    out += "\n\n相关代码证据：\n" + "\n".join(evidence_lines or ["- 未命中代码片段"])
    web_txt = _web_blocks(web_results)
    if web_txt:
        out += "\n\n外部检索摘要：\n" + web_txt
    return out


def _evidence_dict_list(evidence: list[tuple[float, VectorRecord]]) -> list[dict[str, Any]]:
    return [
        {
            "score": score,
            "path": record.metadata.get("path", ""),
            "start_line": record.metadata.get("start_line"),
            "end_line": record.metadata.get("end_line"),
            "preview": record.text.strip()[:360],
        }
        for score, record in evidence
    ]


def _generate_answer_with_llm(
    question: str,
    evidence_dict: list[dict[str, Any]],
    relevant_cards: list[KnowledgeCard],
    llm_provider: str,
    llm_model: str | None,
    *,
    web_results: list[dict[str, Any]] | None,
) -> str:
    try:
        resolved = resolve_llm_provider(llm_provider, llm_model)
        client = create_openai_compatible_client(resolved, timeout=90.0, max_retries=1)
    except (RuntimeError, ImportError):
        return ""

    blocks: list[str] = []
    for i, ev in enumerate(evidence_dict, 1):
        path = ev.get("path", "")
        sl = ev.get("start_line")
        el = ev.get("end_line")
        prev = str(ev.get("preview", ""))
        blocks.append(f"[E{i}] 文件={path} 行={sl}-{el}\n{prev}")
    for j, card in enumerate(relevant_cards, 1):
        blocks.append(f"[C{j}] {card.title}\n{card.summary[:500]}")
    web_txt = _web_blocks(web_results)
    if web_txt:
        blocks.append("外部检索：\n" + web_txt)

    user_payload = (
        "问题：\n"
        + question.strip()
        + "\n\n仅根据下列证据回答；事实须带引用标签如 [E1]、[C2]。"
        "若证据不足请明确说明无法从库中确认，不要编造路径或 API。\n\n"
        + "\n\n".join(blocks)
    )

    try:
        completion = client.chat.completions.create(
            model=resolved.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是严谨的 RAG 助手，只用用户给出的证据块作答，必须使用证据标签引用。",
                },
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        choice = completion.choices[0].message
        text = (choice.content or "").strip()
        return text
    except Exception:
        return ""


def answer_question(
    question: str,
    vector_index: VectorIndex,
    cards: list[KnowledgeCard],
    *,
    top_k: int = 4,
    use_bm25: bool = False,
    use_generative: bool = False,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    web_results: list[dict[str, Any]] | None = None,
    research: ResearchRAGConfig | None = None,
    gold_paths: set[str] | frozenset[str] | None = None,
) -> dict[str, object]:
    evidence, trace = retrieve_evidence_unified(
        question,
        vector_index,
        top_k=top_k,
        use_bm25=use_bm25,
        research=research,
    )
    if research is not None:
        evidence = _minmax_scores(evidence)

    relevant_cards = _select_relevant_cards(question, cards)
    evidence_dict = _evidence_dict_list(evidence)
    abstain_below = research.abstain_confidence_below if research else None

    if use_generative:
        gen = _generate_answer_with_llm(
            question,
            evidence_dict,
            relevant_cards,
            llm_provider,
            llm_model,
            web_results=web_results,
        )
        answer = gen if gen else _build_extractive_answer(relevant_cards, evidence, web_results=web_results)
    else:
        answer = _build_extractive_answer(relevant_cards, evidence, web_results=web_results)

    confidence = _calculate_confidence(evidence, relevant_cards, total_cards=len(cards))
    trace = dict(trace)
    if abstain_below is not None and confidence < float(abstain_below):
        answer = (
            "[abstain] 检索置信度低于阈值，以下为检索摘要而非结论性回答。\n\n" + answer
        )
        trace["abstained"] = True
        trace["abstain_threshold"] = float(abstain_below)
    else:
        trace["abstained"] = False

    out: dict[str, object] = {
        "question": question,
        "answer": answer,
        "cards": [c.to_dict() for c in relevant_cards],
        "evidence": evidence_dict,
        "confidence": confidence,
        "retrieval": {
            "use_bm25": use_bm25,
            "use_generative": use_generative,
            "research": research.to_trace_dict() if research else None,
        },
        "trace": trace,
    }
    if gold_paths is not None:
        out["metrics"] = aggregate_answer_metrics(out, gold_paths=set(gold_paths))
    return out
