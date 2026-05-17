from pathlib import Path

from agent.rag.local_index import build_local_index, retrieve_snippets


def test_retrieve_snippets_finds_overlap(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
    out = retrieve_snippets(ws, "flask api", top_k=2)
    assert out
    assert out[0]["path"] == "a.py"
    assert "line_start" in out[0]


def test_build_local_index_has_metadata(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
    idx = build_local_index(ws)
    assert idx[0]["path"] == "app.py"
    assert idx[0]["suffix"] == ".py"
    assert "flask" in idx[0]["tokens"]


def test_build_local_index_skips_noise_and_marks_truncated(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".pytest_cache").mkdir()
    (ws / ".pytest_cache" / "cached.py").write_text("import flask\n", encoding="utf-8")
    (ws / "app.py").write_text("alpha beta gamma delta epsilon\n", encoding="utf-8")

    idx = build_local_index(ws, max_chars_per_file=12)

    assert [row["path"] for row in idx] == ["app.py"]
    assert idx[0]["truncated"] is True
    assert idx[0]["size_bytes"] > 12
    assert "epsilon" not in idx[0]["text"]


def test_build_local_index_skips_agent_artifacts(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".agent_state.json").write_text('{"goal":"flask api"}\n', encoding="utf-8")
    (ws / "app.py").write_text("from flask import Flask\n", encoding="utf-8")

    idx = build_local_index(ws)

    assert [row["path"] for row in idx] == ["app.py"]


def test_build_local_index_skips_null_byte_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "binary.py").write_bytes(b"import flask\x00hidden\n")

    assert build_local_index(ws) == []


def test_retrieve_snippets_empty_query_returns_entry_files(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("print('entry')\n", encoding="utf-8")
    (ws / "notes.txt").write_text("misc\n", encoding="utf-8")
    out = retrieve_snippets(ws, "", top_k=1)
    assert out
    assert out[0]["path"] == "app.py"


def test_retrieve_snippets_prefers_best_line_window(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("x = 1\n\n\ndef target():\n    return 'flask api route'\n", encoding="utf-8")
    out = retrieve_snippets(ws, "flask route", top_k=1)
    assert out[0]["line_start"] <= 5 <= out[0]["line_end"]
    assert "flask api route" in out[0]["preview"]


def test_retrieve_snippets_includes_source_size_metadata(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")

    out = retrieve_snippets(ws, "flask", top_k=1, max_chars_per_file=10)

    assert out[0]["truncated"] is True
    assert out[0]["size_bytes"] > 10


def test_retrieve_snippets_can_match_path_tokens(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "billing_service.py").write_text("print('no body query term')\n", encoding="utf-8")

    out = retrieve_snippets(ws, "billing", top_k=1)

    assert out
    assert out[0]["path"] == "billing_service.py"


def test_retrieve_snippets_matches_snake_case_subtokens(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("def handler():\n    return missing_symbol\n", encoding="utf-8")

    out = retrieve_snippets(ws, "missing symbol", top_k=1)

    assert out[0]["path"] == "app.py"
    assert {"missing", "symbol"}.issubset(set(out[0]["line_overlap_tokens"]))


def test_retrieve_snippets_matches_camel_case_subtokens(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "client.py").write_text("serviceClient = object()\n", encoding="utf-8")

    out = retrieve_snippets(ws, "service client", top_k=1)

    assert out[0]["path"] == "client.py"
    assert {"service", "client"}.issubset(set(out[0]["line_overlap_tokens"]))
