from pathlib import Path

from agent.tools.workspace_index import build_workspace_index


def test_workspace_index_filters_noise(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    (ws / "__pycache__").mkdir(parents=True)
    (ws / "tests").mkdir(parents=True)
    (ws / "app.py").write_text("print('x')\n", encoding="utf-8")
    (ws / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (ws / ".git" / "config").write_text("[core]\n", encoding="utf-8")

    idx = build_workspace_index(ws)
    assert "app.py" in idx["files"]
    assert "tests/test_app.py" in idx["tests"]
    assert "python" in idx["languages"]
    assert ".git/config" not in idx["files"]
