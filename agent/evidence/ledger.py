"""Build a local evidence ledger from manifests, reports and agent events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _jsonl_count(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except OSError:
        return 0


def _iter_files(roots: list[Path], filename: str, *, limit: int = 120) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if root.is_file() and root.name == filename:
            candidates = [root]
        else:
            candidates = list(root.glob(filename))
            candidates.extend(root.glob(f"*/{filename}"))
            candidates.extend(root.glob(f"*/*/{filename}"))
        for path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved)
            if key in seen or not resolved.is_file():
                continue
            seen.add(key)
            found.append(resolved)
            if len(found) >= limit:
                return found
    return found


def _dedupe_roots(workspace: Path, roots: tuple[Path, ...]) -> list[Path]:
    candidates = [workspace, workspace.parent, *roots]
    out: list[Path] = []
    seen: set[str] = set()
    for root in candidates:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if not resolved.exists():
            continue
        key = str(resolved)
        if key not in seen:
            out.append(resolved)
            seen.add(key)
    return out


def build_evidence_ledger(
    workspace: Path,
    *,
    roots: tuple[Path, ...] = (),
    write_path: Path | None = None,
) -> dict[str, Any]:
    search_roots = _dedupe_roots(workspace, roots)
    entries: list[dict[str, Any]] = []
    for path in _iter_files(search_roots, "run_manifest.json"):
        raw = _safe_json(path)
        entries.append(
            {
                "type": "run_manifest",
                "path": str(path),
                "kind": raw.get("kind"),
                "manifest_id": raw.get("manifest_id"),
                "evaluation_score": (raw.get("evaluation") or {}).get("overall_score") if isinstance(raw.get("evaluation"), dict) else None,
                "source_refs": len(raw.get("source_refs", [])) if isinstance(raw.get("source_refs"), list) else 0,
                "risks": raw.get("risks", []) if isinstance(raw.get("risks"), list) else [],
            }
        )
    for path in _iter_files(search_roots, "solution_manifest.json"):
        raw = _safe_json(path)
        entries.append(
            {
                "type": "solution_manifest",
                "path": str(path),
                "template": raw.get("template"),
                "stack": raw.get("stack"),
                "training_eligible": raw.get("training_eligible"),
                "quality_score": raw.get("quality_score") or (raw.get("quality") or {}).get("score") if isinstance(raw.get("quality"), dict) else raw.get("quality_score"),
            }
        )
    for path in _iter_files(search_roots, "evaluation_report.json"):
        raw = _safe_json(path)
        entries.append(
            {
                "type": "evaluation_report",
                "path": str(path),
                "stage": raw.get("stage"),
                "overall_score": raw.get("overall_score"),
                "grade": raw.get("grade"),
            }
        )
    for path in _iter_files(search_roots, "governance_report.json"):
        raw = _safe_json(path)
        entries.append(
            {
                "type": "governance_report",
                "path": str(path),
                "ok": raw.get("ok"),
                "risk_level": raw.get("risk_level"),
                "issues": len(raw.get("issues", [])) if isinstance(raw.get("issues"), list) else 0,
            }
        )
    events_path = workspace / ".agent_events.jsonl"
    if events_path.exists():
        entries.append({"type": "agent_events", "path": str(events_path), "events": _jsonl_count(events_path)})
    counts: dict[str, int] = {}
    for entry in entries:
        typ = str(entry.get("type", "unknown"))
        counts[typ] = counts.get(typ, 0) + 1
    ledger = {
        "schema": "evidence_ledger.v1",
        "workspace": str(workspace.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {"total": len(entries), "by_type": counts},
        "entries": entries,
    }
    if write_path:
        target = write_path.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger["written_to"] = str(target)
    return ledger
