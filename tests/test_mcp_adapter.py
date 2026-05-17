from pathlib import Path

from agent.mcp import adapter as adapter_mod
from agent.mcp.adapter import MCP_TOOL_REGISTRY, default_mcp_capabilities, invoke_mcp_tool


def test_mcp_capabilities_not_empty() -> None:
    caps = default_mcp_capabilities()
    assert caps
    assert any(c["name"] == "workspace.search" for c in caps)
    assert any(c["tool"] == "workspace.search" for c in caps)
    assert any(c["name"] == "workspace.verify" for c in caps)
    search = next(c for c in caps if c["tool"] == "workspace.search")
    verify = next(c for c in caps if c["tool"] == "workspace.verify")
    assert search["args_schema"]["properties"]["top_k"]["maximum"] == 10
    assert verify["args_schema"]["properties"]["timeout"]["maximum"] == 600.0


def test_mcp_capabilities_match_registry() -> None:
    caps = default_mcp_capabilities()
    tools = [c["tool"] for c in caps]
    assert tools == list(MCP_TOOL_REGISTRY.keys())
    assert len(tools) == len(set(tools))
    assert all(MCP_TOOL_REGISTRY[t].handler for t in tools)
    assert all(c["args_schema"] == MCP_TOOL_REGISTRY[c["tool"]].args_schema for c in caps)


def test_mcp_capabilities_do_not_expose_registry_schema_by_reference() -> None:
    caps = default_mcp_capabilities()
    search = next(c for c in caps if c["tool"] == "workspace.search")
    search["args_schema"]["properties"]["top_k"]["maximum"] = 999
    assert MCP_TOOL_REGISTRY["workspace.search"].args_schema["properties"]["top_k"]["maximum"] == 10


def test_mcp_workspace_search(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("import flask\n", encoding="utf-8")
    out = invoke_mcp_tool(ws, "workspace.search", {"query": "flask"})
    assert out["ok"] is True
    assert out["tool"] == "workspace.search"
    assert out["results"]
    assert "line_start" in out["results"][0]


def test_mcp_workspace_search_clamps_bad_top_k(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, int] = {}

    def fake_retrieve_snippets(workspace: Path, query: str, *, top_k: int):
        seen["top_k"] = top_k
        return []

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(adapter_mod, "retrieve_snippets", fake_retrieve_snippets)
    out = invoke_mcp_tool(ws, "workspace.search", {"query": "flask", "top_k": 999})
    assert out["ok"] is True
    assert seen["top_k"] == 10


def test_mcp_unsupported_tool(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    out = invoke_mcp_tool(ws, "unknown.tool", {})
    assert out["ok"] is False


def test_mcp_rejects_non_object_args(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    out = invoke_mcp_tool(ws, "workspace.search", [])  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["error"] == "args must be object"


def test_mcp_workspace_verify(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("x = 1\n", encoding="utf-8")
    out = invoke_mcp_tool(ws, "workspace.verify", {"include_pytest": False})
    assert out["ok"] is True
    assert out["tool"] == "workspace.verify"
    assert out["report"]["summary"]["python_files"] == 1


def test_mcp_workspace_verify_normalizes_bool_and_caps_timeout(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run_production_checks(workspace: Path, *, include_pytest: bool, timeout: float) -> dict:
        seen["include_pytest"] = include_pytest
        seen["timeout"] = timeout
        return {"ok": True, "summary": {"python_files": 0}}

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(adapter_mod, "run_production_checks", fake_run_production_checks)
    out = invoke_mcp_tool(ws, "workspace.verify", {"include_pytest": "false", "timeout": 9999})
    assert out["ok"] is True
    assert seen["include_pytest"] is False
    assert seen["timeout"] == 600.0


def test_mcp_workspace_verify_returns_error_for_bad_timeout(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    out = invoke_mcp_tool(ws, "workspace.verify", {"timeout": "slow"})
    assert out["ok"] is False
    assert out["error"] == "timeout must be number"
