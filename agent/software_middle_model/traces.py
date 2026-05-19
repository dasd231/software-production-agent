"""Trace collection for the software middle-layer small model.

The trace layer is deliberately simple: JSONL records that can later become
supervised examples for a small model.  It never starts training and never calls
remote services.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import MiddleModelInput


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_number(value: Any, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in {float("inf"), float("-inf")}:
        return default
    return number


def build_middle_model_trace(
    model_input: MiddleModelInput | dict[str, Any],
    decision: dict[str, Any],
    *,
    final_accepted: bool | None = None,
    latency_saved_ms: float | int | None = None,
    quality_delta: float | int | None = None,
    source_trace_id: str = "",
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one JSON-serializable training trace record.

    ``final_accepted`` can stay ``None`` when the immediate outcome is unknown.
    Later review/evaluation jobs can backfill this field by joining on
    ``trace_id`` or ``source_trace_id``.
    """

    inp = model_input if isinstance(model_input, MiddleModelInput) else MiddleModelInput.from_dict(model_input)
    decision_block = decision.get("decision", {}) if isinstance(decision.get("decision"), dict) else {}
    selected_id = str(decision_block.get("selected_candidate_id", "") or "")
    should_run_rules = bool(decision_block.get("should_run_expensive_rules", True))
    recommended_mode = str(decision_block.get("recommended_mode", "") or "")
    labels = {
        "final_accepted": final_accepted,
        "shortcut_success": None if final_accepted is None else bool(final_accepted and not should_run_rules),
        "selected_candidate_id": selected_id,
        "should_run_expensive_rules": should_run_rules,
        "recommended_mode": recommended_mode,
        "latency_saved_ms": _finite_number(latency_saved_ms, default=0.0),
        "quality_delta": _finite_number(quality_delta, default=0.0),
    }
    return {
        "schema": "software_middle_model_trace.v1",
        "trace_id": str(uuid.uuid4()),
        "source_trace_id": str(source_trace_id or ""),
        "created_at": _now_iso(),
        "task": inp.task,
        "model_hint": inp.model_hint,
        "features": inp.features,
        "candidates": list(inp.candidates),
        "decision": decision_block,
        "ranked_candidates": decision.get("ranked_candidates", []) if isinstance(decision.get("ranked_candidates"), list) else [],
        "thresholds": decision.get("thresholds", {}) if isinstance(decision.get("thresholds"), dict) else {},
        "backend": decision.get("backend", {}) if isinstance(decision.get("backend"), dict) else {},
        "labels": labels,
        "outcome": dict(outcome or {}),
    }


def append_middle_model_trace(path: Path, trace: dict[str, Any]) -> dict[str, Any]:
    """Append a trace record as JSONL and return write metadata."""

    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(trace, ensure_ascii=False, sort_keys=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return {
        "path": str(target),
        "bytes": len((line + "\n").encode("utf-8")),
        "trace_id": str(trace.get("trace_id", "")),
        "schema": str(trace.get("schema", "")),
    }


def load_middle_model_traces(path: Path) -> list[dict[str, Any]]:
    """Load valid JSONL traces, skipping malformed lines for robustness."""

    target = path.resolve()
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows
