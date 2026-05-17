"""Publish a successful workspace run as a reusable solution asset."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.runtime.manifest import build_run_manifest, write_run_manifest
from agent.solution_library.manifest import normalise_solution_manifest


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return text.strip("._") or "solution"


def _safe_read(path: Path, max_chars: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _load_existing_manifest(workspace: Path) -> dict[str, Any]:
    try:
        raw = json.loads((workspace / "solution_manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _artifact_hints(workspace: Path, limit: int = 40) -> list[str]:
    hints: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).as_posix()
        if rel.startswith(".agent_") or "__pycache__" in rel or rel.startswith(".git/"):
            continue
        if rel in {"README.md", "solution_manifest.json"} or rel.startswith("docs/") or rel.startswith("backend/") or rel.startswith("frontend/") or rel.startswith("preview/"):
            hints.append(rel)
        if len(hints) >= limit:
            break
    return hints


def _has_file(workspace: Path, *patterns: str) -> bool:
    return any(next(workspace.rglob(pattern), None) is not None for pattern in patterns)


def _infer_stack(workspace: Path) -> str:
    stack: list[str] = []
    if _has_file(workspace, "pom.xml"):
        stack.append("Spring Boot")
    if _has_file(workspace, "package.json"):
        package_text = "\n".join(_safe_read(path, max_chars=2000) for path in workspace.rglob("package.json"))
        if "vue" in package_text.lower():
            stack.append("Vue")
        elif "react" in package_text.lower():
            stack.append("React")
        else:
            stack.append("Node")
    if _has_file(workspace, "requirements.txt", "pyproject.toml", "*.py"):
        stack.append("Python")
    if _has_file(workspace, "Dockerfile", "docker-compose.yml"):
        stack.append("Docker")
    return " + ".join(dict.fromkeys(stack)) or "unknown"


def _infer_tags(workspace: Path, title: str) -> list[str]:
    haystack = " ".join(
        [
            title,
            _safe_read(workspace / "README.md", max_chars=4000),
            _safe_read(workspace / "docs" / "PRODUCT_SPEC.md", max_chars=4000),
        ]
    ).lower()
    rules = {
        "auth": ("login", "auth", "rbac", "登录", "权限", "角色"),
        "workflow": ("workflow", "approval", "审批", "流程"),
        "crud": ("crud", "增删改查", "create", "update", "delete"),
        "audit": ("audit", "审计", "日志"),
        "import-export": ("import", "export", "导入", "导出"),
        "frontend-backend": ("frontend", "backend", "前端", "后端", "接口"),
        "management-system": ("management", "管理", "dashboard", "后台"),
    }
    tags = [name for name, tokens in rules.items() if any(token in haystack for token in tokens)]
    tags.extend(["published-solution", "software-production"])
    return list(dict.fromkeys(tags))


def _backup_text(workspace: Path, title: str) -> str:
    existing = _safe_read(workspace / "docs" / "SOLUTION_BACKUP.md", max_chars=10000)
    if existing.strip():
        return existing
    readme = _safe_read(workspace / "README.md", max_chars=6000)
    return "\n".join(
        [
            f"# Solution Backup: {title}",
            "",
            "## Source README Preview",
            "",
            readme or "No README.md found.",
            "",
            "## Reuse Boundary",
            "",
            "- Reuse architecture, workflow and delivery checklist first.",
            "- Verify license, secrets and business fit before reuse or training.",
            "- Use evidence ledger and evaluation reports to decide training eligibility.",
            "",
        ]
    )


def publish_solution_from_run(
    workspace: Path,
    *,
    output_dir: Path | None = None,
    title: str = "",
    source_type: str = "product_run",
    accepted_by: str = "",
    acceptance_note: str = "",
) -> dict[str, Any]:
    root = workspace.resolve()
    existing = _load_existing_manifest(root)
    solution_title = title.strip() or str(existing.get("template") or root.name)
    dest_root = (output_dir or (root / "published_solution")).resolve()
    dest = dest_root / _safe_name(solution_title)
    docs = dest / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    backup = _backup_text(root, solution_title)
    accepted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = normalise_solution_manifest(
        {
            **existing,
            "schema": existing.get("schema", "solution_manifest.v1"),
            "source_type": source_type,
            "template": solution_title,
            "goal": existing.get("goal") or f"Published solution from run {root.name}",
            "stack": existing.get("stack") or _infer_stack(root),
            "retrieval_tags": existing.get("retrieval_tags") or _infer_tags(root, solution_title),
            "artifact_hints": existing.get("artifact_hints") or _artifact_hints(root),
            "source_run": str(root),
            "acceptance_status": "accepted",
            "accepted_at": accepted_at,
            "accepted_by": accepted_by.strip() or "operator",
            "acceptance_note": acceptance_note.strip(),
            "reuse_boundary": existing.get("reuse_boundary") or "reuse plan, architecture and delivery pattern; inspect source before code reuse",
            "training_eligible": bool(existing.get("training_eligible", False)),
        }
    )
    (dest / "solution_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (docs / "SOLUTION_BACKUP.md").write_text(backup, encoding="utf-8")
    readme = root / "README.md"
    if readme.exists():
        shutil.copy2(readme, dest / "README.source.md")
    files = {
        "solution_manifest": str(dest / "solution_manifest.json"),
        "solution_backup": str(docs / "SOLUTION_BACKUP.md"),
        "solutions_dir": str(dest_root),
    }
    run_manifest = build_run_manifest(
        kind="solution_publish",
        input_summary={
            "workspace": str(root),
            "title": solution_title,
            "source_type": source_type,
            "acceptance_status": "accepted",
            "accepted_by": accepted_by.strip() or "operator",
        },
        files=files,
        evaluation=manifest.get("evaluation") if isinstance(manifest.get("evaluation"), dict) else {},
        artifacts=[str(dest)],
        source_refs=[{"type": "workspace", "path": str(root)}],
        risks=["manual_license_privacy_review_required"],
    )
    manifest_path = write_run_manifest(dest, run_manifest)
    files["run_manifest"] = str(manifest_path)
    return {
        "schema": "solution_publish_result.v1",
        "ok": True,
        "source_workspace": str(root),
        "published_dir": str(dest),
        "files": files,
        "manifest": manifest,
        "run_manifest": run_manifest,
    }
