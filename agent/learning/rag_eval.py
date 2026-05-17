"""RAG 轻量评测指标（无标注时的代理量 + 有路径标注时的命中率）。

用于发刊实验记录、与 trace 一并写入 JSONL，便于后续画表；非 RAGAS 全量实现。
"""

from __future__ import annotations

import re
from typing import Any


def evidence_path_hit_rate(evidence: list[dict[str, Any]], gold_paths: set[str]) -> float:
    """证据列表中 `path` 命中任一 gold 相对路径的比例（0~1）。"""
    if not evidence or not gold_paths:
        return 0.0
    hits = 0
    for row in evidence:
        p = str(row.get("path", "") or "").replace("\\", "/")
        if p and p in gold_paths:
            hits += 1
    return hits / len(evidence)


def citation_tag_coverage(answer: str, n_evidence: int) -> dict[str, Any]:
    """从回答中解析 [E1]…[En] 形式引用，返回覆盖率与缺失列表。"""
    if n_evidence <= 0:
        return {"coverage": 0.0, "tags_found": [], "tags_missing": []}
    found: set[int] = set()
    for m in re.finditer(r"\[E\s*(\d+)\s*\]", answer, flags=re.IGNORECASE):
        try:
            found.add(int(m.group(1)))
        except ValueError:
            continue
    expected = set(range(1, n_evidence + 1))
    missing = sorted(expected - found)
    coverage = len(found & expected) / n_evidence if n_evidence else 0.0
    return {"coverage": coverage, "tags_found": sorted(found), "tags_missing": missing}


def aggregate_answer_metrics(
    answer_payload: dict[str, Any],
    *,
    gold_paths: set[str] | None = None,
) -> dict[str, Any]:
    """对 `answer_question` 返回 dict 做一次汇总，便于写入实验日志。"""
    evidence = answer_payload.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    ans = str(answer_payload.get("answer", "") or "")
    n_ev = len(evidence)
    out: dict[str, Any] = {
        "confidence": answer_payload.get("confidence"),
        "n_evidence": n_ev,
        "citation": citation_tag_coverage(ans, n_ev),
        "trace_keys": sorted((answer_payload.get("trace") or {}).keys()) if isinstance(answer_payload.get("trace"), dict) else [],
    }
    if gold_paths:
        out["path_hit_rate"] = evidence_path_hit_rate(evidence, gold_paths)
    return out
