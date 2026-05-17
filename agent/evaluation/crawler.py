"""Evaluation for GitHub/local repository crawl profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.evaluation.schemas import Metric, MetricReport, clamp_score
from agent.learning.schemas import RepoCandidate, StructureSummary


def _has_ci(structure: StructureSummary) -> bool:
    return any(path.startswith(".github/workflows/") or path.lower().endswith("gitlab-ci.yml") for path in structure.files)


def _has_docs(structure: StructureSummary) -> bool:
    names = {Path(path).name.lower() for path in structure.files}
    return any(path.lower().startswith("docs/") for path in structure.files) or bool(names & {"readme.md", "architecture.md"})


def _boolean_metric(name: str, value: bool, *, weight: float, detail: str = "") -> Metric:
    return Metric(name=name, value=bool(value), score=10.0 if value else 0.0, weight=weight, status="ok" if value else "missing", detail=detail)


def _architecture_metric(arch: dict[str, Any]) -> Metric:
    shape = str(arch.get("shape", "unknown") or "unknown")
    score = 10.0 if shape == "fullstack" else 6.0 if shape in {"frontend", "backend"} else 0.0
    detail = "frontend/backend pair" if shape == "fullstack" else shape
    return Metric("architecture_coverage", shape, score, weight=2.0, status="ok" if score else "missing", detail=detail)


def _popularity_metric(stars: int) -> Metric:
    if stars >= 1000:
        score = 10.0
        status = "popular"
    elif stars >= 100:
        score = 6.0
        status = "known"
    else:
        score = 2.0 if stars > 0 else 0.0
        status = "low_signal"
    return Metric("popularity", stars, score, weight=0.8, status=status, detail="GitHub stars")


def _structure_metric(structure: StructureSummary) -> Metric:
    return Metric(
        "structure_complete",
        not bool(structure.truncated),
        10.0 if not structure.truncated else 5.0,
        weight=0.7,
        status="ok" if not structure.truncated else "truncated",
        detail="structure parser was not truncated",
    )


def evaluate_repo_profile(
    candidate: RepoCandidate,
    structure: StructureSummary,
    arch: dict[str, Any],
    readme_summary: str,
) -> MetricReport:
    metrics = (
        _architecture_metric(arch),
        _boolean_metric("package_manifest", bool(structure.package_files), weight=1.0, detail="package/build manifest present"),
        _boolean_metric("entrypoints", bool(structure.entrypoints), weight=1.0, detail="runtime entrypoints detected"),
        _boolean_metric("tests", bool(structure.tests), weight=1.4, detail="test files detected"),
        _boolean_metric("docs", _has_docs(structure) or bool(readme_summary.strip()), weight=1.0, detail="README/docs available"),
        _boolean_metric("ci", _has_ci(structure), weight=0.7, detail="CI workflow detected"),
        _boolean_metric("license", bool(candidate.license_spdx), weight=0.7, detail="license metadata available"),
        _popularity_metric(int(candidate.stargazers_count or 0)),
        _structure_metric(structure),
    )
    summary = {
        "repo": candidate.full_name,
        "shape": arch.get("shape", "unknown"),
        "tags": list(arch.get("tags", [])),
        "files": len(structure.files),
    }
    return MetricReport(stage="crawler.repo_profile", metrics=metrics, summary=summary)


def repo_quality_summary(report: MetricReport) -> dict[str, Any]:
    reasons: list[str] = []
    arch = report.metric("architecture_coverage")
    if arch and arch.value == "fullstack":
        reasons.append("frontend_backend_pair")
    elif arch and arch.value in {"frontend", "backend"}:
        reasons.append(f"{arch.value}_only")
    for name, reason in (
        ("package_manifest", "package_manifest"),
        ("entrypoints", "entrypoints"),
        ("tests", "tests"),
        ("docs", "docs"),
        ("ci", "ci"),
        ("license", "license"),
    ):
        metric = report.metric(name)
        if metric and bool(metric.value):
            reasons.append(reason)
    popularity = report.metric("popularity")
    if popularity and int(popularity.value or 0) >= 1000:
        reasons.append("popular")
    elif popularity and int(popularity.value or 0) >= 100:
        reasons.append("known_project")
    structure = report.metric("structure_complete")
    if structure and not bool(structure.value):
        reasons.append("structure_truncated")
    return {"score": clamp_score(report.overall_score), "reasons": reasons}


def evaluate_crawl_run(profiles: list[dict[str, Any]], exported_solutions: list[str]) -> MetricReport:
    profile_count = len(profiles)
    exported_count = len(exported_solutions)
    scores = [float(profile.get("quality", {}).get("score", 0.0) or 0.0) for profile in profiles]
    high_quality = sum(1 for score in scores if score >= 6.5)
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    metrics = (
        Metric("profile_count", profile_count, 10.0 if profile_count else 0.0, weight=1.0, status="ok" if profile_count else "empty"),
        Metric("average_repo_quality", avg_score, avg_score, weight=2.0, status="ok" if avg_score >= 6.5 else "watch"),
        Metric("high_quality_rate", round(high_quality / profile_count, 4) if profile_count else 0.0, 10.0 * high_quality / profile_count if profile_count else 0.0, weight=1.0),
        Metric("exported_solution_count", exported_count, 10.0 if exported_count else 2.0 if profile_count else 0.0, weight=1.0),
    )
    return MetricReport(
        stage="crawler.run",
        metrics=metrics,
        summary={
            "profiles": profile_count,
            "exported_solutions": exported_count,
            "average_repo_quality": avg_score,
        },
    )
