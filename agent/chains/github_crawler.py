"""GitHub frontend/backend crawler, profiler, and solution-library exporter.

The crawler is intentionally architecture-extensible: new stacks are added as
rules, not as one-off branches. It can run fully offline with local repos, or
use GitHub Search when network crawling is explicitly enabled.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.evaluation.crawler import evaluate_crawl_run, evaluate_repo_profile, repo_quality_summary
from agent.learning.filters import filter_repositories
from agent.learning.github_search import GitHubSearchClient
from agent.learning.readme_parser import parse_readme
from agent.learning.repo_downloader import download_repo
from agent.learning.schemas import RepoCandidate, StructureSummary
from agent.learning.structure_parser import parse_structure
from agent.runtime.manifest import build_run_manifest, write_run_manifest
from agent.solution_library.manifest import build_github_solution_manifest


@dataclass(frozen=True)
class ArchitectureRule:
    name: str
    family: str
    tags: tuple[str, ...]
    file_markers: tuple[str, ...] = ()
    path_markers: tuple[str, ...] = ()
    content_markers: tuple[str, ...] = ()
    min_hits: int = 1


@dataclass(frozen=True)
class CrawlProfileInput:
    query: str
    output_dir: Path
    local_repos: tuple[Path, ...] = ()
    enable_github_network: bool = False
    repo_limit: int = 5
    min_stars: int = 50
    allowed_licenses: tuple[str, ...] = ()
    updated_after: str = ""
    quality_threshold: float = 6.5


@dataclass(frozen=True)
class CrawlProfileResult:
    output_dir: str
    profiles: list[dict[str, Any]]
    exported_solutions: list[str] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "profiles": self.profiles,
            "exported_solutions": self.exported_solutions,
            "files": self.files,
            "evaluation": self.evaluation,
            "manifest": self.manifest,
        }


ARCHITECTURE_RULES: tuple[ArchitectureRule, ...] = (
    ArchitectureRule(
        name="spring-boot",
        family="backend",
        tags=("java", "spring-boot", "rest-api"),
        file_markers=("pom.xml", "build.gradle"),
        content_markers=("spring-boot", "@SpringBootApplication", "@RestController"),
    ),
    ArchitectureRule(
        name="vue",
        family="frontend",
        tags=("vue", "spa", "frontend"),
        file_markers=("package.json", "vite.config.js", "vue.config.js"),
        path_markers=(".vue",),
        content_markers=('"vue"', "@vitejs/plugin-vue"),
    ),
    ArchitectureRule(
        name="react",
        family="frontend",
        tags=("react", "spa", "frontend"),
        file_markers=("package.json", "vite.config.js", "next.config.js"),
        path_markers=(".jsx", ".tsx"),
        content_markers=('"react"', "next"),
    ),
    ArchitectureRule(
        name="node-express",
        family="backend",
        tags=("node", "express", "rest-api"),
        file_markers=("package.json",),
        content_markers=('"express"', "express()"),
    ),
    ArchitectureRule(
        name="python-api",
        family="backend",
        tags=("python", "api"),
        file_markers=("requirements.txt", "pyproject.toml"),
        path_markers=("app.py", "main.py"),
        content_markers=("fastapi", "flask", "django"),
    ),
)


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return text.strip("._") or "repo"


def _candidate_from_local(path: Path) -> RepoCandidate:
    path = path.resolve()
    return RepoCandidate(
        full_name=f"local/{path.name}",
        html_url=f"file://{path}",
        description="Local repository supplied to GitHub crawler.",
        stargazers_count=0,
        license_spdx="LOCAL",
        updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        local_path=str(path),
    )


def _read_small_files(root: Path, structure: StructureSummary, max_files: int = 60, max_chars: int = 1200) -> str:
    chunks: list[str] = []
    priority_names = {
        "package.json",
        "pom.xml",
        "build.gradle",
        "pyproject.toml",
        "requirements.txt",
        "README.md",
        "vite.config.js",
        "next.config.js",
    }
    selected = sorted(
        structure.files,
        key=lambda p: (Path(p).name not in priority_names, len(Path(p).parts), p),
    )[:max_files]
    for rel in selected:
        path = root / rel
        if path.suffix.lower() not in {".json", ".xml", ".gradle", ".toml", ".txt", ".md", ".py", ".java", ".js", ".ts", ".vue"}:
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace")[:max_chars])
        except OSError:
            continue
    return "\n".join(chunks).lower()


def _marker_hits(rule: ArchitectureRule, *, structure: StructureSummary, content: str) -> int:
    files = set(structure.files)
    names = {Path(p).name for p in files}
    hit = 0
    for marker in rule.file_markers:
        if marker in names or marker in files:
            hit += 1
    for marker in rule.path_markers:
        marker_l = marker.lower()
        if any(marker_l in path.lower() for path in files):
            hit += 1
    for marker in rule.content_markers:
        if marker.lower() in content:
            hit += 1
    return hit


def detect_architecture(root: Path, structure: StructureSummary) -> dict[str, Any]:
    content = _read_small_files(root, structure)
    matched: list[dict[str, Any]] = []
    tags: list[str] = []
    families: dict[str, list[str]] = {"frontend": [], "backend": [], "other": []}
    for rule in ARCHITECTURE_RULES:
        hits = _marker_hits(rule, structure=structure, content=content)
        if hits < rule.min_hits:
            continue
        matched.append({"name": rule.name, "family": rule.family, "hits": hits, "tags": list(rule.tags)})
        families.setdefault(rule.family, []).append(rule.name)
        for tag in rule.tags:
            if tag not in tags:
                tags.append(tag)
    if families.get("frontend") and families.get("backend"):
        shape = "fullstack"
        tags.append("frontend-backend")
    elif families.get("frontend"):
        shape = "frontend"
    elif families.get("backend"):
        shape = "backend"
    else:
        shape = "unknown"
    return {
        "shape": shape,
        "frontend": families.get("frontend", []),
        "backend": families.get("backend", []),
        "matched_rules": matched,
        "tags": tags,
    }


def score_repo_quality(candidate: RepoCandidate, structure: StructureSummary, arch: dict[str, Any], readme_summary: str) -> dict[str, Any]:
    report = evaluate_repo_profile(candidate, structure, arch, readme_summary)
    return repo_quality_summary(report)


def _solution_backup(profile: dict[str, Any]) -> str:
    repo = profile["repo"]
    arch = profile["architecture"]
    quality = profile["quality"]
    return "\n".join(
        [
            f"# Solution Backup: {repo.get('full_name')}",
            "",
            "## Source",
            "",
            f"- URL: {repo.get('html_url')}",
            f"- License: {repo.get('license_spdx') or 'unknown'}",
            f"- Stars: {repo.get('stargazers_count')}",
            "",
            "## Architecture Tags",
            "",
            *[f"- {tag}" for tag in arch.get("tags", [])],
            "",
            "## Quality",
            "",
            f"- Score: {quality.get('score')}",
            *[f"- {reason}" for reason in quality.get("reasons", [])],
            "",
            "## Reuse Guidance",
            "",
            "- Reuse architecture shape and delivery checklist, not blindly copied code.",
            "- Verify license compatibility before training or product reuse.",
            "- Prefer projects with tests, package manifests, docs and clear frontend/backend separation.",
            "- Convert high-quality patterns into SFT samples through `training_prepare`.",
            "",
        ]
    )


def _export_solution(profile: dict[str, Any], solutions_dir: Path) -> Path:
    repo_name = _safe_name(str(profile["repo"].get("full_name", profile.get("workspace", "repo"))))
    dest = solutions_dir / repo_name
    docs = dest / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    manifest = build_github_solution_manifest(profile)
    (dest / "solution_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (docs / "SOLUTION_BACKUP.md").write_text(_solution_backup(profile), encoding="utf-8")
    return dest


def _profile_repo(candidate: RepoCandidate, workspace: Path) -> dict[str, Any]:
    readme = parse_readme(workspace)
    structure = parse_structure(workspace)
    arch = detect_architecture(workspace, structure)
    arch["matched_rule_names"] = [row["name"] for row in arch.get("matched_rules", [])]
    evaluation_report = evaluate_repo_profile(candidate, structure, arch, readme.summary)
    quality = repo_quality_summary(evaluation_report)
    training_tags = list(dict.fromkeys(arch.get("tags", []) + quality.get("reasons", [])))
    return {
        "repo": candidate.to_dict(),
        "workspace": str(workspace),
        "readme": readme.to_dict(),
        "structure": structure.to_dict(),
        "architecture": arch,
        "quality": quality,
        "evaluation": evaluation_report.to_dict(),
        "training_tags": training_tags,
        "training_priority": "high" if quality["score"] >= 7.5 else "medium" if quality["score"] >= 5.5 else "low",
    }


def _write_report(path: Path, profiles: list[dict[str, Any]], exported: list[str], evaluation: dict[str, Any]) -> None:
    lines = ["# GitHub Frontend/Backend Crawl Report", ""]
    lines.append(f"Profiles: {len(profiles)}")
    lines.append(f"Exported solutions: {len(exported)}")
    lines.append(f"Evaluation: {evaluation.get('overall_score', 0)} ({evaluation.get('grade', 'n/a')})")
    lines.append("")
    for profile in profiles:
        repo = profile["repo"]
        arch = profile["architecture"]
        quality = profile["quality"]
        lines.extend(
            [
                f"## {repo.get('full_name')}",
                "",
                f"- Shape: `{arch.get('shape')}`",
                f"- Tags: `{', '.join(arch.get('tags', []))}`",
                f"- Quality: `{quality.get('score')}`",
                f"- Reasons: `{', '.join(quality.get('reasons', []))}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def crawl_frontend_backend_repos(inp: CrawlProfileInput) -> CrawlProfileResult:
    output_dir = inp.output_dir.resolve()
    repos_dir = output_dir / "repos"
    solutions_dir = output_dir / "solutions"
    output_dir.mkdir(parents=True, exist_ok=True)
    repos_dir.mkdir(parents=True, exist_ok=True)
    solutions_dir.mkdir(parents=True, exist_ok=True)

    candidates = [_candidate_from_local(path) for path in inp.local_repos]
    if inp.enable_github_network and inp.query.strip():
        candidates.extend(GitHubSearchClient().search(inp.query, per_page=max(int(inp.repo_limit) * 3, 5)))
    candidates = filter_repositories(
        candidates,
        min_stars=max(int(inp.min_stars), 0),
        allowed_licenses=inp.allowed_licenses,
        updated_after=inp.updated_after,
        max_count=max(int(inp.repo_limit), 1),
    )

    profiles: list[dict[str, Any]] = []
    exported: list[str] = []
    for candidate in candidates:
        workspace = download_repo(candidate, repos_dir)
        profile = _profile_repo(candidate, workspace)
        if float(profile["quality"]["score"]) >= float(inp.quality_threshold):
            exported_path = _export_solution(profile, solutions_dir)
            profile["exported_solution"] = str(exported_path)
            exported.append(str(exported_path))
        profiles.append(profile)

    profiles_path = output_dir / "repo_profiles.json"
    candidates_path = output_dir / "candidates.json"
    evaluation_path = output_dir / "evaluation_report.json"
    report_path = output_dir / "report.md"
    evaluation = evaluate_crawl_run(profiles, exported).to_dict()
    profiles_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates_path.write_text(json.dumps([c.to_dict() for c in candidates], ensure_ascii=False, indent=2), encoding="utf-8")
    evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(report_path, profiles, exported, evaluation)
    files = {
        "profiles": str(profiles_path),
        "candidates": str(candidates_path),
        "evaluation_report": str(evaluation_path),
        "report": str(report_path),
        "solutions_dir": str(solutions_dir),
    }
    manifest = build_run_manifest(
        kind="github_crawl_profile",
        input_summary={
            "query": inp.query,
            "local_repos": [str(path) for path in inp.local_repos],
            "github": bool(inp.enable_github_network),
            "repo_limit": inp.repo_limit,
            "quality_threshold": inp.quality_threshold,
        },
        files=files,
        evaluation=evaluation,
        artifacts=exported,
        source_refs=[candidate.to_dict() for candidate in candidates],
        risks=[] if not inp.enable_github_network else ["network_repo_metadata_requires_license_review"],
    )
    manifest_path = write_run_manifest(output_dir, manifest)
    files["run_manifest"] = str(manifest_path)
    return CrawlProfileResult(
        output_dir=str(output_dir),
        profiles=profiles,
        exported_solutions=exported,
        files=files,
        evaluation=evaluation,
        manifest=manifest,
    )
