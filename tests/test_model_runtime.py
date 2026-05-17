from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.core.executor import run_action
from agent.llm.runtime import model_runtime_status
from agent.resources.registry import discover_resources


class _ModelHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"ok": True, "model": "local-test-model", "device": "cpu"})
            return
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [{"id": "local-test-model", "object": "model"}]})
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        return

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _server() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{srv.server_port}/v1"


def test_model_runtime_status_probes_local_openai_compatible_server(monkeypatch) -> None:
    srv, base_url = _server()
    monkeypatch.setenv("MAIN_DEEPSEEK_BASE_URL", base_url)
    monkeypatch.setenv("MAIN_DEEPSEEK_MODEL", "local-test-model")
    try:
        out = model_runtime_status("main_deepseek", probe=True, timeout=2)
    finally:
        srv.shutdown()

    assert out["schema"] == "model_runtime_status.v1"
    assert out["provider"] == "main_deepseek"
    assert out["local_endpoint"] is True
    assert out["serving_hint"] == "local_openai_compatible"
    assert out["probe"]["ok"] is True
    assert out["probe"]["models"] == ["local-test-model"]


def test_model_runtime_action_can_skip_probe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAIN_DEEPSEEK_BASE_URL", "http://127.0.0.1:65530/v1")
    ws = tmp_path / "ws"
    ws.mkdir()

    out = run_action(
        ws,
        {"type": "action", "action": "model_runtime_status", "args": {"provider": "main_deepseek", "probe": False}},
    )

    assert out["ok"] is True
    assert out["status"]["schema"] == "model_runtime_status.v1"
    assert out["status"]["probe"]["checked"] is False


def test_resource_registry_exposes_model_runtime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MAIN_DEEPSEEK_BASE_URL", "http://127.0.0.1:8000/v1")
    ws = tmp_path / "ws"
    ws.mkdir()

    registry = discover_resources(ws, type_filter="model_runtime")

    assert registry["summary"]["by_type"]["model_runtime"] == 1
    runtime = registry["resources"][0]
    assert runtime["name"] == "MAIN DEEPSEEK"
    assert runtime["metadata"]["schema"] == "model_runtime_status.v1"
    assert runtime["metadata"]["probe"]["checked"] is False
