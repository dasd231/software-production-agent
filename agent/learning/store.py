"""Load and query an existing learning run.

函数流程图：
    load_learning_cards(output_dir)
      -> knowledge_cards.json
      -> list[KnowledgeCard]

    ask_learning_run(output_dir, question, top_k)
      -> VectorIndex.load_jsonl(vector_index.jsonl)
      -> load_learning_cards()
      -> answer_question()
      -> append answer to answers.jsonl
      -> return answer dict

你可以继续练算法/工程化的点：
    1. 多库查询：现在单 output_dir；可合并多个 learning run 或按标签路由。
    2. 历史问答：answers.jsonl 可用于评测集和用户反馈训练。
    3. 召回策略：可增加 path/language/license filters 和 reranker。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.learning.rag_pipeline import ResearchRAGConfig
from agent.learning.rag_qa import answer_question
from agent.learning.schemas import KnowledgeCard
from agent.learning.vector_store import VectorIndex


class LearningStoreError(RuntimeError):
    pass


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value]


def load_learning_cards(output_dir: Path) -> list[KnowledgeCard]:
    path = output_dir / "knowledge_cards.json"
    if not path.exists():
        raise LearningStoreError(f"missing knowledge_cards.json: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise LearningStoreError("knowledge_cards.json must be an array")
    cards: list[KnowledgeCard] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cards.append(
            KnowledgeCard(
                title=str(item.get("title", "")),
                summary=str(item.get("summary", "")),
                tags=_string_list(item.get("tags")),
                source_paths=_string_list(item.get("source_paths")),
                questions=_string_list(item.get("questions")),
            )
        )
    return cards


def append_answer_jsonl(output_dir: Path, answer: dict[str, Any]) -> Path:
    path = output_dir / "answers.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(answer, ensure_ascii=False) + "\n")
    return path


def ask_learning_run(
    output_dir: Path,
    question: str,
    top_k: int = 4,
    *,
    use_bm25: bool = False,
    use_generative: bool = False,
    llm_provider: str = "openai",
    llm_model: str | None = None,
    research: ResearchRAGConfig | None = None,
    gold_paths: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    index_path = output_dir / "vector_index.jsonl"
    if not index_path.exists():
        raise LearningStoreError(f"missing vector_index.jsonl: {index_path}")
    index = VectorIndex.load_jsonl(index_path)
    cards = load_learning_cards(output_dir)
    web_results: list[dict[str, Any]] | None = None
    web_path = output_dir / "web_results.json"
    if web_path.exists():
        try:
            raw = json.loads(web_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                web_results = [x for x in raw if isinstance(x, dict)]
        except json.JSONDecodeError:
            web_results = None
    answer = answer_question(
        question,
        index,
        cards,
        top_k=top_k,
        use_bm25=use_bm25,
        use_generative=use_generative,
        llm_provider=llm_provider,
        llm_model=llm_model,
        web_results=web_results,
        research=research,
        gold_paths=gold_paths,
    )
    append_answer_jsonl(output_dir, answer)
    return answer
