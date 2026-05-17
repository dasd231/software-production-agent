"""Evaluation and promotion policy for learned knowledge assets.

The learning pipeline can ingest many repositories, but only repositories that
clear this gate should be published into the reusable knowledge store or used
to prepare downstream training data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.evaluation.schemas import Metric, MetricReport, clamp_score
from agent.learning.schemas import RepoLearningArtifact


SECTION_GROUPS: dict[str, tuple[str, ...]] = {
    "setup": ("install", "installation", "setup", "getting started", "quick start"),
    "usage": ("usage", "run", "example", "examples", "quick start"),
    "testing": ("test", "tests", "testing"),
}


@dataclass(frozen=True)
class KnowledgePromotionPolicy:
    """Hard blockers applied before an artifact is promoted downstream."""

    min_overall_score: float = 6.5
    min_traceability_rate: float = 0.6
    require_readme: bool = True
    require_slices: bool = True
    require_cards: bool = True
    block_failed_sandbox: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_overall_score": clamp_score(self.min_overall_score),
            "min_traceability_rate": round(max(0.0, min(float(self.min_traceability_rate), 1.0)), 4),
            "require_readme": self.require_readme,
            "require_slices": self.require_slices,
            "require_cards": self.require_cards,
            "block_failed_sandbox": self.block_failed_sandbox,
        }


def _section_groups_present(sections: dict[str, str]) -> set[str]:
    headings = [str(name).lower() for name in sections]
    found: set[str] = set()
    for group, aliases in SECTION_GROUPS.items():
        if any(any(alias in heading for alias in aliases) for heading in headings):
            found.add(group)
    return found


def _slice_count_score(count: int) -> float:
    if count >= 12:
        return 10.0
    if count >= 6:
        return 8.0
    if count >= 3:
        return 6.5
    if count >= 1:
        return 4.0
    return 0.0


def _citation_stats(artifact: RepoLearningArtifact) -> tuple[float, float, int, int]:
    cards = artifact.cards
    traced_cards = sum(1 for card in cards if card.source_paths)
    traceability_rate = traced_cards / len(cards) if cards else 0.0

    known_paths = set(artifact.structure.files)
    citation_paths = [path for card in cards for path in card.source_paths]
    valid_citations = sum(1 for path in citation_paths if path in known_paths)
    validity_rate = valid_citations / len(citation_paths) if citation_paths else 0.0
    return traceability_rate, validity_rate, len(citation_paths), valid_citations


def _structure_readiness(artifact: RepoLearningArtifact) -> tuple[int, list[str]]:
    present: list[str] = []
    if artifact.structure.entrypoints:
        present.append("entrypoints")
    if artifact.structure.tests:
        present.append("tests")
    if artifact.structure.package_files:
        present.append("package_manifest")
    return len(present), present


def _sandbox_metric(artifact: RepoLearningArtifact) -> Metric:
    if artifact.sandbox is None:
        return Metric(
            "sandbox_health",
            "skipped",
            8.0,
            weight=1.0,
            status="skipped",
            detail="sandbox check was not requested",
        )
    return Metric(
        "sandbox_health",
        artifact.sandbox.ok,
        10.0 if artifact.sandbox.ok else 0.0,
        weight=1.0,
        status="ok" if artifact.sandbox.ok else "failed",
        detail="static sandbox checks passed" if artifact.sandbox.ok else "sandbox checks failed",
    )


def evaluate_knowledge_asset(artifact: RepoLearningArtifact) -> MetricReport:
    """Score one repository artifact before publication into the knowledge base."""

    section_groups = _section_groups_present(artifact.readme.sections)
    traceability_rate, citation_validity_rate, citation_count, valid_citations = _citation_stats(artifact)
    readiness_count, readiness_parts = _structure_readiness(artifact)
    readme_present = bool(artifact.readme.path)
    metrics = (
        Metric(
            "readme_presence",
            readme_present,
            10.0 if readme_present else 0.0,
            weight=1.4,
            status="ok" if readme_present else "missing",
            detail="README file exists",
        ),
        Metric(
            "readme_section_coverage",
            sorted(section_groups),
            len(section_groups) / len(SECTION_GROUPS) * 10.0,
            weight=0.8,
            status="ok" if len(section_groups) >= 2 else "watch",
            detail="install/usage/testing-style sections detected",
        ),
        Metric(
            "card_traceability_rate",
            round(traceability_rate, 4),
            traceability_rate * 10.0,
            weight=1.6,
            status="ok" if traceability_rate >= 0.8 else "watch",
            detail="knowledge cards with at least one source path",
        ),
        Metric(
            "citation_validity_rate",
            round(citation_validity_rate, 4),
            citation_validity_rate * 10.0,
            weight=1.4,
            status="ok" if citation_validity_rate >= 0.8 else "watch",
            detail="card source paths that exist in parsed repository files",
        ),
        Metric(
            "slice_count",
            len(artifact.slices),
            _slice_count_score(len(artifact.slices)),
            weight=1.0,
            status="ok" if len(artifact.slices) >= 3 else "watch",
            detail="retrievable source slices",
        ),
        Metric(
            "structure_readiness",
            readiness_parts,
            readiness_count / 3.0 * 10.0,
            weight=1.2,
            status="ok" if readiness_count >= 2 else "watch",
            detail="entrypoints/tests/package manifest coverage",
        ),
        _sandbox_metric(artifact),
        Metric(
            "structure_complete",
            not artifact.structure.truncated,
            10.0 if not artifact.structure.truncated else 5.0,
            weight=0.6,
            status="ok" if not artifact.structure.truncated else "truncated",
            detail="structure parsing was not truncated",
        ),
    )
    return MetricReport(
        stage="learning.knowledge_asset",
        metrics=metrics,
        summary={
            "repo": artifact.repo.full_name,
            "cards": len(artifact.cards),
            "slices": len(artifact.slices),
            "files": len(artifact.structure.files),
            "citation_paths": citation_count,
            "valid_citation_paths": valid_citations,
        },
    )


def knowledge_quality_summary(report: MetricReport) -> dict[str, Any]:
    traceability = report.metric("card_traceability_rate")
    validity = report.metric("citation_validity_rate")
    return {
        "score": report.overall_score,
        "grade": report.grade,
        "traceability_rate": traceability.value if traceability else 0.0,
        "citation_validity_rate": validity.value if validity else 0.0,
    }


def decide_knowledge_promotion(
    artifact: RepoLearningArtifact,
    report: MetricReport,
    *,
    policy: KnowledgePromotionPolicy | None = None,
) -> dict[str, Any]:
    """Apply hard blockers and return an auditable promotion decision."""

    policy = policy or KnowledgePromotionPolicy()
    blockers: list[str] = []
    warnings: list[str] = []

    traceability_metric = report.metric("card_traceability_rate")
    traceability = float(traceability_metric.value) if traceability_metric else 0.0

    if policy.require_readme and not artifact.readme.path:
        blockers.append("missing_readme")
    if policy.require_slices and not artifact.slices:
        blockers.append("no_code_slices")
    if policy.require_cards and not artifact.cards:
        blockers.append("no_knowledge_cards")
    if policy.block_failed_sandbox and artifact.sandbox is not None and not artifact.sandbox.ok:
        blockers.append("sandbox_failed")
    if traceability < policy.min_traceability_rate:
        blockers.append("traceability_below_threshold")
    if report.overall_score < policy.min_overall_score:
        blockers.append("quality_score_below_threshold")

    if artifact.sandbox is None:
        warnings.append("sandbox_skipped")
    if not artifact.structure.tests:
        warnings.append("missing_tests")
    if not artifact.structure.package_files:
        warnings.append("missing_package_manifest")
    if artifact.structure.truncated:
        warnings.append("structure_truncated")

    eligible = not blockers
    return {
        "repo": artifact.repo.full_name,
        "eligible": eligible,
        "decision": "promoted" if eligible else "rejected",
        "reasons": ["passed_quality_gate"] if eligible else blockers,
        "warnings": warnings,
        "score": report.overall_score,
        "grade": report.grade,
    }
