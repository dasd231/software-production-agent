from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            current.append(ch)
        else:
            if current:
                out.append("".join(current))
                current = []
    if current:
        out.append("".join(current))
    return out


def _bow(text: str, vocab: list[str]) -> list[float]:
    counts = Counter(_tokens(text))
    return [float(counts.get(token, 0)) for token in vocab]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa = {str(x).strip().lower() for x in a if str(x).strip()}
    sb = {str(x).strip().lower() for x in b if str(x).strip()}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / max(len(sa | sb), 1)


def _jacobi_eigenvalues(matrix: list[list[float]], *, max_iter: int = 80, eps: float = 1e-10) -> list[float]:
    """Small symmetric-matrix eigenvalue solver; avoids numpy for test/runtime portability."""

    n = len(matrix)
    if n == 0:
        return []
    a = [[float(matrix[i][j]) for j in range(n)] for i in range(n)]
    for _ in range(max_iter):
        p, q = 0, 1 if n > 1 else 0
        max_val = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                val = abs(a[i][j])
                if val > max_val:
                    max_val = val
                    p, q = i, j
        if max_val < eps or p == q:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        phi = 0.5 * math.atan2(2.0 * apq, aqq - app)
        c = math.cos(phi)
        s = math.sin(phi)
        for i in range(n):
            if i not in (p, q):
                aip, aiq = a[i][p], a[i][q]
                a[i][p] = a[p][i] = c * aip - s * aiq
                a[i][q] = a[q][i] = s * aip + c * aiq
        a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0
    return [max(a[i][i], 0.0) for i in range(n)]


def _effective_rank(vectors: list[list[float]]) -> float:
    n = len(vectors)
    if n == 0:
        return 0.0
    normalized: list[list[float]] = []
    for vec in vectors:
        norm = math.sqrt(sum(x * x for x in vec))
        normalized.append([x / norm for x in vec] if norm else [0.0 for x in vec])
    gram = [[_cosine(normalized[i], normalized[j]) for j in range(n)] for i in range(n)]
    eigs = [x for x in _jacobi_eigenvalues(gram) if x > 1e-9]
    total = sum(eigs)
    if total <= 0:
        return 0.0
    probs = [x / total for x in eigs]
    entropy = -sum(p * math.log(p) for p in probs if p > 0)
    return math.exp(entropy)


def assess_similarity_collapse(
    rationales: list[str],
    evidence_sets: list[list[str]] | None = None,
    *,
    pairwise_threshold: float = 0.82,
    rank_ratio_threshold: float = 0.45,
    evidence_jaccard_threshold: float = 0.72,
    min_agents: int = 3,
) -> dict[str, Any]:
    clean = [str(item).strip() for item in rationales if str(item).strip()]
    evidence_sets = evidence_sets or []
    vocab = sorted({token for item in clean for token in _tokens(item)})
    vectors = [_bow(item, vocab) for item in clean]

    similarities: list[float] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            similarities.append(_cosine(vectors[i], vectors[j]))
    avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
    max_similarity = max(similarities) if similarities else 0.0
    rank = _effective_rank(vectors)
    rank_ratio = rank / max(len(vectors), 1)

    evidence_similarities: list[float] = []
    for i in range(len(evidence_sets)):
        for j in range(i + 1, len(evidence_sets)):
            evidence_similarities.append(_jaccard(evidence_sets[i], evidence_sets[j]))
    evidence_jaccard = sum(evidence_similarities) / len(evidence_similarities) if evidence_similarities else 0.0

    enough_agents = len(clean) >= min_agents
    high_text_similarity = avg_similarity >= pairwise_threshold or max_similarity >= min(pairwise_threshold + 0.08, 0.98)
    low_rank = rank_ratio <= rank_ratio_threshold and len(clean) >= 2
    evidence_homogeneous = evidence_jaccard >= evidence_jaccard_threshold and len(evidence_sets) >= 2
    alarm = bool(enough_agents and ((high_text_similarity and low_rank) or (high_text_similarity and evidence_homogeneous)))
    severity = "none"
    if alarm:
        severity = "critical" if high_text_similarity and low_rank and evidence_homogeneous else "warning"

    return {
        "schema": "similarity_collapse_assessment.v1",
        "alarm": alarm,
        "severity": severity,
        "agent_count": len(clean),
        "metrics": {
            "avg_pairwise_rationale_cosine": round(avg_similarity, 4),
            "max_pairwise_rationale_cosine": round(max_similarity, 4),
            "effective_rank": round(rank, 4),
            "effective_rank_ratio": round(rank_ratio, 4),
            "avg_evidence_jaccard": round(evidence_jaccard, 4),
        },
        "thresholds": {
            "pairwise_threshold": pairwise_threshold,
            "rank_ratio_threshold": rank_ratio_threshold,
            "evidence_jaccard_threshold": evidence_jaccard_threshold,
            "min_agents": min_agents,
        },
        "triggers": {
            "enough_agents": enough_agents,
            "high_text_similarity": high_text_similarity,
            "low_effective_rank": low_rank,
            "evidence_homogeneous": evidence_homogeneous,
        },
        "recommended_interventions": [
            "rewind_to_blind_fanout",
            "inject_heterogeneous_model_or_temperature",
            "force_new_evidence_sources",
            "retain_minority_hypothesis_verbatim",
            "route_to_adversarial_verifier",
        ]
        if alarm
        else ["continue_normal_consensus"],
    }


def build_diversity_retention_decision(messages: list[dict[str, Any]], *, retain_k: int = 3) -> dict[str, Any]:
    rationales = [str(item.get("rationale", item.get("content", "")) or "") for item in messages]
    evidence = [list(item.get("evidence", [])) if isinstance(item.get("evidence", []), list) else [] for item in messages]
    assessment = assess_similarity_collapse(rationales, evidence)
    if not messages:
        retained: list[dict[str, Any]] = []
    else:
        vocab = sorted({token for text in rationales for token in _tokens(text)})
        vectors = [_bow(text, vocab) for text in rationales]
        avg_vector = [sum(vec[i] for vec in vectors) / max(len(vectors), 1) for i in range(len(vocab))]
        scored = []
        for idx, item in enumerate(messages):
            disagreement = 1.0 - _cosine(vectors[idx], avg_vector) if vocab else 0.0
            evidence_novelty = 1.0 - max((_jaccard(evidence[idx], evidence[j]) for j in range(len(evidence)) if j != idx), default=0.0)
            scored.append((0.7 * disagreement + 0.3 * evidence_novelty, idx, item))
        retained = [item for _score, _idx, item in sorted(scored, reverse=True)[: max(1, retain_k)]]
    return {
        "schema": "diversity_retention_decision.v1",
        "assessment": assessment,
        "input_count": len(messages),
        "retained_count": len(retained),
        "retained_messages": retained,
        "policy": "retain messages farthest from majority rationale and evidence set",
    }
