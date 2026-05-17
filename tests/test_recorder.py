import json
from pathlib import Path

import pytest

from agent.recorder import SCHEMA_VERSION, append_event, build_event_row, build_run_id


def test_build_event_row_adds_stable_contract_fields() -> None:
    row = build_event_row(
        "custom",
        {"schema_version": "old", "event_id": "old-id", "value": 3},
        ts=12.5,
        event_id="fixed-id",
    )
    assert row["ts"] == 12.5
    assert row["kind"] == "custom"
    assert row["schema_version"] == SCHEMA_VERSION
    assert row["event_id"] == "fixed-id"
    assert row["value"] == 3


def test_build_run_id_is_short_and_unique() -> None:
    a = build_run_id("workspace")
    b = build_run_id("workspace")
    assert len(a) == 16
    assert len(b) == 16
    assert a != b


def test_append_event_writes_jsonl_with_event_id_and_safe_defaults(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    append_event(
        p,
        "sample",
        {
            "path": tmp_path / "x.py",
            "tags": {"b", "a"},
            "blob": b"hello",
        },
    )
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "sample"
    assert row["schema_version"] == SCHEMA_VERSION
    assert isinstance(row["event_id"], str)
    assert len(row["event_id"]) == 16
    assert row["path"].endswith("x.py")
    assert row["tags"] == ["a", "b"]
    assert row["blob"] == "hello"


def test_append_event_none_path_is_noop() -> None:
    append_event(None, "sample", {"value": 1})


def test_append_event_strict_raises_for_unwritable_target(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        append_event(tmp_path, "sample", {"value": 1}, strict=True)
