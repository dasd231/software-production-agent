"""Versioned solution manifest helpers."""

from __future__ import annotations

from typing import Any


SOLUTION_SCHEMA_VERSION = "solution_manifest.v2"
LIBRARY_READY_ACCEPTANCE_STATUSES = frozenset({"accepted", "curated", "accepted_legacy"})


def normalise_solution_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    retrieval_tags = [str(x) for x in raw.get("retrieval_tags", [])] if isinstance(raw.get("retrieval_tags"), list) else []
    architecture_tags = [str(x) for x in raw.get("architecture_tags", [])] if isinstance(raw.get("architecture_tags"), list) else []
    if not architecture_tags:
        architecture_tags = retrieval_tags[:]
    quality = raw.get("quality") if isinstance(raw.get("quality"), dict) else {}
    out = dict(raw)
    out.setdefault("schema", "solution_manifest.v1")
    out["schema_version"] = str(out.get("schema_version") or SOLUTION_SCHEMA_VERSION)
    out["source_type"] = str(out.get("source_type") or "unknown")
    explicit_acceptance = str(out.get("acceptance_status") or "").strip()
    if explicit_acceptance:
        acceptance_status = explicit_acceptance
    elif out["source_type"] == "github_profile":
        acceptance_status = "curated"
    elif out["source_type"] in {"product_run", "product_run_candidate"}:
        acceptance_status = "candidate"
    else:
        acceptance_status = "accepted_legacy"
    out["acceptance_status"] = acceptance_status
    out["accepted_at"] = str(out.get("accepted_at") or "")
    out["accepted_by"] = str(out.get("accepted_by") or "")
    out["source_run"] = str(out.get("source_run") or "")
    out["architecture_tags"] = architecture_tags
    out["retrieval_tags"] = retrieval_tags
    out["quality_score"] = float(out.get("quality_score") or quality.get("score") or 0.0)
    out["reuse_boundary"] = str(out.get("reuse_boundary") or "reuse architecture and delivery pattern; verify license before code reuse")
    out["training_eligible"] = bool(out.get("training_eligible", out["quality_score"] >= 6.5))
    out["embedding_indexed"] = bool(out.get("embedding_indexed", False))
    return out


def is_solution_library_ready(raw: dict[str, Any]) -> bool:
    manifest = normalise_solution_manifest(raw)
    return str(manifest.get("acceptance_status", "")) in LIBRARY_READY_ACCEPTANCE_STATUSES


def build_github_solution_manifest(profile: dict[str, Any]) -> dict[str, Any]:
    arch = profile["architecture"]
    quality = profile["quality"]
    manifest = {
        "schema": "solution_manifest.v1",
        "schema_version": SOLUTION_SCHEMA_VERSION,
        "source_type": "github_profile",
        "acceptance_status": "curated",
        "accepted_by": "github_crawler",
        "template": "-".join(arch.get("matched_rule_names", [])[:3]) or "github-profile",
        "stack": " + ".join(arch.get("tags", [])[:5]) or "unknown",
        "goal": f"GitHub profile reusable solution: {profile['repo'].get('full_name')}",
        "retrieval_tags": arch.get("tags", []) + quality.get("reasons", []),
        "architecture_tags": arch.get("tags", []),
        "artifact_hints": profile["structure"].get("package_files", []) + profile["structure"].get("entrypoints", []) + profile["structure"].get("tests", [])[:5],
        "source_repo": profile["repo"],
        "quality": quality,
        "quality_score": quality.get("score", 0.0),
        "evaluation": profile.get("evaluation", {}),
        "reuse_boundary": "Reuse architecture shape, delivery checklist and test strategy; do not copy code blindly.",
        "training_eligible": float(quality.get("score", 0.0) or 0.0) >= 6.5,
        "embedding_indexed": False,
    }
    return normalise_solution_manifest(manifest)
