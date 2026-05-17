"""Training data exporter for learning pipeline artifacts.

函数流程图：
    build_training_examples(artifacts, vector_index, query)
      -> card QA examples
      -> code explanation examples
      -> optional RAG answer example
      -> list[TrainingExample]

    save_training_examples_jsonl(path, examples)
      -> one JSON object per line
      -> citations preserve repo/path/line trace

你可以继续练算法/工程化的点：
    1. 样本质量：现在是规则样本；可接 LLM 生成 instruction/output，并用引用校验。
    2. 数据去重：可按 example_id/source_hash/simhash 去重。
    3. 训练格式：可导出 OpenAI fine-tune messages、ShareGPT、Alpaca、RAG eval 等格式。
    4. 许可过滤：可把 repo license 和 allowlist 绑定到样本导出策略。
    5. 负样本：可从低相关检索结果构造 hard negative，用于检索模型训练。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent.learning.rag_qa import answer_question
from agent.learning.schemas import RepoLearningArtifact, TrainingExample
from agent.learning.vector_store import VectorIndex


def _stable_id(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=10)
    for part in parts:
        h.update(part.encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _citation(repo: str, path: str, start_line: int | None = None, end_line: int | None = None) -> dict[str, object]:
    out: dict[str, object] = {"repo": repo, "path": path}
    if start_line is not None:
        out["start_line"] = start_line
    if end_line is not None:
        out["end_line"] = end_line
    return out


def _card_examples(artifact: RepoLearningArtifact, max_per_repo: int = 12) -> list[TrainingExample]:
    examples: list[TrainingExample] = []
    repo = artifact.repo.full_name
    for card in artifact.cards[:max_per_repo]:
        for question in card.questions[:2]:
            citations = [_citation(repo, path) for path in card.source_paths]
            examples.append(
                TrainingExample(
                    example_id=_stable_id("card_qa", repo, card.title, question),
                    task_type="knowledge_card_qa",
                    instruction="根据给定项目知识卡回答问题，回答必须忠于输入材料并保留引用。",
                    input=(
                        f"问题：{question}\n\n"
                        f"知识卡标题：{card.title}\n"
                        f"标签：{', '.join(card.tags)}\n"
                        f"摘要：{card.summary}\n"
                        f"来源：{', '.join(card.source_paths) if card.source_paths else 'N/A'}"
                    ),
                    output=card.summary,
                    citations=citations,
                    metadata={"repo": repo, "card_title": card.title, "license": artifact.repo.license_spdx},
                )
            )
    return examples


def _code_examples(artifact: RepoLearningArtifact, max_per_repo: int = 20) -> list[TrainingExample]:
    examples: list[TrainingExample] = []
    repo = artifact.repo.full_name
    for sl in artifact.slices[:max_per_repo]:
        output = (
            f"这段代码来自 `{sl.path}` 第 {sl.start_line}-{sl.end_line} 行。"
            f"主要可学习的关键词包括：{', '.join(sl.tokens[:12]) or 'N/A'}。"
        )
        examples.append(
            TrainingExample(
                example_id=_stable_id("code_explain", repo, sl.slice_id, sl.text[:120]),
                task_type="code_explanation",
                instruction="解释给定代码片段的作用，并指出可学习的实现关键词。",
                input=f"文件：{sl.path}\n行号：{sl.start_line}-{sl.end_line}\n语言：{sl.language}\n\n```text\n{sl.text[:2600]}\n```",
                output=output,
                citations=[_citation(repo, sl.path, sl.start_line, sl.end_line)],
                metadata={"repo": repo, "language": sl.language, "license": artifact.repo.license_spdx},
            )
        )
    return examples


def _rag_example(
    artifacts: list[RepoLearningArtifact],
    vector_index: VectorIndex,
    query: str,
) -> list[TrainingExample]:
    query = query.strip()
    if not query or not artifacts or not vector_index.records:
        return []
    cards = [card for artifact in artifacts for card in artifact.cards]
    answer = answer_question(query, vector_index, cards)
    evidence = answer.get("evidence", [])
    citations = []
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            citations.append(
                {
                    "path": item.get("path", ""),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "score": item.get("score"),
                }
            )
    return [
        TrainingExample(
            example_id=_stable_id("rag_answer", query, str(len(vector_index.records))),
            task_type="rag_grounded_answer",
            instruction="基于检索证据回答问题，必须列出相关代码证据。",
            input=f"问题：{query}",
            output=str(answer.get("answer", "")),
            citations=citations,
            metadata={"query": query, "vector_records": len(vector_index.records)},
        )
    ]


def _candidate_rag_queries(
    artifacts: list[RepoLearningArtifact],
    *,
    seed_query: str = "",
    extra_queries: tuple[str, ...] = (),
    limit: int = 1,
) -> list[str]:
    """Select deterministic grounded-answer prompts for training export."""

    max_queries = max(int(limit), 0)
    if max_queries <= 0:
        return []
    candidates: list[str] = []
    for raw in (seed_query, *extra_queries):
        query = str(raw or "").strip()
        if query:
            candidates.append(query)
    for artifact in artifacts:
        for card in artifact.cards:
            candidates.extend(str(question or "").strip() for question in card.questions if str(question or "").strip())
    seen: set[str] = set()
    out: list[str] = []
    for query in candidates:
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= max_queries:
            break
    return out


def build_training_examples(
    artifacts: list[RepoLearningArtifact],
    vector_index: VectorIndex,
    query: str = "",
    *,
    rag_queries: tuple[str, ...] = (),
    rag_query_limit: int = 1,
) -> list[TrainingExample]:
    examples: list[TrainingExample] = []
    for artifact in artifacts:
        examples.extend(_card_examples(artifact))
        examples.extend(_code_examples(artifact))
    for rag_query in _candidate_rag_queries(
        artifacts,
        seed_query=query,
        extra_queries=rag_queries,
        limit=rag_query_limit,
    ):
        examples.extend(_rag_example(artifacts, vector_index, rag_query))
    seen: set[str] = set()
    deduped: list[TrainingExample] = []
    for example in examples:
        if example.example_id in seen:
            continue
        seen.add(example.example_id)
        deduped.append(example)
    return deduped


def save_training_examples_jsonl(path: Path, examples: list[TrainingExample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example.to_dict(), ensure_ascii=False) + "\n")
