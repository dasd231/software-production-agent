import pytest

from agent.core import executor as executor_mod
from agent.core.executor import ExecutionLimits, ExecutorError, parse_action, run_action, run_action_guarded
from pathlib import Path


def test_write_read_roundtrip(tmp_path: Path) -> None:
    lim = ExecutionLimits(max_write_bytes=10000, default_command_timeout=30.0)
    w = tmp_path / "ws"
    w.mkdir()
    run_action(
        w,
        {"type": "action", "action": "write_file", "args": {"path": "x.txt", "content": "abc"}},
        limits=lim,
    )
    r = run_action(w, {"type": "action", "action": "read_file", "args": {"path": "x.txt"}}, limits=lim)
    assert r["content"] == "abc"


def test_command_blocklist(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    with pytest.raises(ExecutorError, match="blocked"):
        run_action(
            w,
            {"type": "action", "action": "run_command", "args": {"command": "rm -rf /"}},
            limits=lim,
        )


def test_guarded_action_blocks_missing_permission(tmp_path: Path) -> None:
    w = tmp_path / "ws"
    w.mkdir()

    result = run_action_guarded(
        w,
        {"type": "action", "action": "write_file", "args": {"path": "x.txt", "content": "abc"}},
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )

    assert result["ok"] is False
    assert result["error_code"] == "PERMISSION_DENIED"
    assert result["preflight"]["status"] == "permission_denied"
    assert result["recommended_action"] == "request_permission_or_use_allowed_action"


def test_guarded_action_requires_confirmation_for_high_risk_actions(tmp_path: Path) -> None:
    w = tmp_path / "ws"
    w.mkdir()

    result = run_action_guarded(
        w,
        {"type": "action", "action": "git_init", "args": {}},
        limits=ExecutionLimits(granted_permissions=frozenset({"repo:write"})),
    )

    assert result["ok"] is False
    assert result["error_code"] == "CONFIRMATION_REQUIRED"
    assert result["preflight"]["requires_confirmation"] is True


def test_guarded_action_wraps_timeout_with_standard_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        command = "python slow.py"
        returncode = -1
        stdout = ""
        stderr = "[timeout]"
        cwd = "ws"

        def ok(self) -> bool:
            return False

    def fake_run_shell(command: str, *, cwd: Path, timeout: float) -> FakeResult:
        return FakeResult()

    w = tmp_path / "ws"
    w.mkdir()
    monkeypatch.setattr(executor_mod, "run_shell", fake_run_shell)

    result = run_action_guarded(
        w,
        {"type": "action", "action": "run_command", "args": {"command": "python slow.py", "timeout": 1}},
    )

    assert result["ok"] is False
    assert result["error_code"] == "TIMEOUT"
    assert result["retryable"] is True
    assert result["recommended_action"] == "retry_with_narrower_scope_or_longer_timeout"
    assert result["preflight"]["status"] == "allowed"
    assert result["duration_ms"] >= 0


def test_run_command_rejects_non_positive_timeout(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    with pytest.raises(ExecutorError, match="timeout must be positive"):
        run_action(
            w,
            {"type": "action", "action": "run_command", "args": {"command": "python -V", "timeout": 0}},
            limits=lim,
        )


def test_run_command_rejects_non_finite_timeout(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    with pytest.raises(ExecutorError, match="timeout must be finite"):
        run_action(
            w,
            {"type": "action", "action": "run_command", "args": {"command": "python -V", "timeout": float("nan")}},
            limits=lim,
        )


def test_run_command_caps_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, float] = {}

    class FakeResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

        def ok(self) -> bool:
            return True

        def feedback_block(self) -> str:
            return ""

    def fake_run_shell(command: str, *, cwd: Path, timeout: float) -> FakeResult:
        seen["timeout"] = timeout
        return FakeResult()

    lim = ExecutionLimits(default_command_timeout=30.0, max_command_timeout=45.0)
    w = tmp_path / "ws"
    w.mkdir()
    monkeypatch.setattr(executor_mod, "run_shell", fake_run_shell)
    r = run_action(
        w,
        {"type": "action", "action": "run_command", "args": {"command": "python -V", "timeout": 9999}},
        limits=lim,
    )
    assert r["ok"] is True
    assert seen["timeout"] == 45.0


def test_run_command_clips_large_output_head_and_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        command = "python noisy.py"
        returncode = 1
        stdout = "START-" + ("x" * 80) + "-END"
        stderr = "ERR-" + ("y" * 80) + "-TAIL"
        cwd = "ws"

        def ok(self) -> bool:
            return False

    def fake_run_shell(command: str, *, cwd: Path, timeout: float) -> FakeResult:
        return FakeResult()

    lim = ExecutionLimits(default_command_timeout=30.0, max_command_output_chars=40)
    w = tmp_path / "ws"
    w.mkdir()
    monkeypatch.setattr(executor_mod, "run_shell", fake_run_shell)
    r = run_action(
        w,
        {"type": "action", "action": "run_command", "args": {"command": "python noisy.py"}},
        limits=lim,
    )
    assert r["ok"] is False
    assert r["stdout_truncated"] is True
    assert r["stderr_truncated"] is True
    assert len(r["stdout"]) == 40
    assert r["stdout"].startswith("START-")
    assert r["stdout"].endswith("-END")
    assert "...[truncated]..." in r["feedback"]


def test_oversized_write(tmp_path: Path) -> None:
    lim = ExecutionLimits(max_write_bytes=10, default_command_timeout=30.0)
    w = tmp_path / "ws"
    w.mkdir()
    with pytest.raises(ExecutorError, match="max_write_bytes"):
        run_action(
            w,
            {"type": "action", "action": "write_file", "args": {"path": "big.txt", "content": "x" * 50}},
            limits=lim,
        )


def test_parse_action_line() -> None:
    d = parse_action('{"type":"action","action":"list_files","args":{}}')
    assert d["action"] == "list_files"


def test_workspace_index_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    (w / "app.py").write_text("print('ok')\n", encoding="utf-8")
    r = run_action(w, {"type": "action", "action": "workspace_index", "args": {}}, limits=lim)
    assert r["ok"] is True
    assert "index" in r
    assert "app.py" in r["index"]["files"]


def test_mcp_call_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    (w / "note.txt").write_text("flask api\n", encoding="utf-8")
    r = run_action(
        w,
        {
            "type": "action",
            "action": "mcp_call",
            "args": {"tool": "workspace.search", "args": {"query": "flask"}},
        },
        limits=lim,
    )
    assert r["ok"] is True
    assert r["action"] == "mcp_call"
    assert r["tool"] == "workspace.search"


def test_mcp_capabilities_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    r = run_action(w, {"type": "action", "action": "mcp_capabilities", "args": {}}, limits=lim)
    assert r["ok"] is True
    assert r["action"] == "mcp_capabilities"
    assert isinstance(r["capabilities"], list)
    assert len(r["capabilities"]) >= 1
    assert "args_schema" in r["capabilities"][0]


def test_production_check_action_success(tmp_path: Path) -> None:
    lim = ExecutionLimits(default_command_timeout=30.0)
    w = tmp_path / "ws"
    w.mkdir()
    (w / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    r = run_action(
        w,
        {"type": "action", "action": "production_check", "args": {"include_pytest": False}},
        limits=lim,
    )
    assert r["ok"] is True
    assert r["report"]["summary"]["python_files"] == 1


def test_production_check_action_syntax_failure(tmp_path: Path) -> None:
    lim = ExecutionLimits(default_command_timeout=30.0)
    w = tmp_path / "ws"
    w.mkdir()
    (w / "bad.py").write_text("def nope(:\n    pass\n", encoding="utf-8")
    r = run_action(
        w,
        {"type": "action", "action": "production_check", "args": {"include_pytest": False}},
        limits=lim,
    )
    assert r["ok"] is False
    assert r["report"]["summary"]["compile_failures"] == 1


def test_production_check_caps_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, float] = {}

    def fake_run_production_checks(workspace: Path, *, include_pytest: bool, timeout: float) -> dict:
        seen["timeout"] = timeout
        return {"ok": True, "summary": {"python_files": 0, "compile_failures": 0}}

    lim = ExecutionLimits(default_command_timeout=30.0, max_command_timeout=40.0)
    w = tmp_path / "ws"
    w.mkdir()
    monkeypatch.setattr(executor_mod, "run_production_checks", fake_run_production_checks)
    r = run_action(
        w,
        {"type": "action", "action": "production_check", "args": {"include_pytest": False, "timeout": 120}},
        limits=lim,
    )
    assert r["ok"] is True
    assert seen["timeout"] == 40.0


def test_chain_registry_action(tmp_path: Path) -> None:
    w = tmp_path / "ws"
    w.mkdir()

    r = run_action(w, {"type": "action", "action": "chain_registry", "args": {"name": "research"}})

    assert r["ok"] is True
    assert r["chain"]["action"] == "research_synthesize"
    assert r["chain"]["evaluation_stage"] == "research.synthesis"


def test_resource_registry_action(tmp_path: Path) -> None:
    w = tmp_path / "ws"
    w.mkdir()

    r = run_action(w, {"type": "action", "action": "resource_registry", "args": {"type": "chain"}})

    assert r["ok"] is True
    assert r["schema"] == "resource_registry.v1"
    assert r["summary"]["by_type"]["chain"] >= 1


def test_model_runtime_status_action_without_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIN_DEEPSEEK_BASE_URL", "http://127.0.0.1:65530/v1")
    w = tmp_path / "ws"
    w.mkdir()

    r = run_action(
        w,
        {"type": "action", "action": "model_runtime_status", "args": {"provider": "main_deepseek", "probe": False}},
    )

    assert r["ok"] is True
    assert r["status"]["provider"] == "main_deepseek"
    assert r["status"]["probe"]["checked"] is False


def test_workflow_validate_action(tmp_path: Path) -> None:
    w = tmp_path / "ws"
    w.mkdir()

    r = run_action(
        w,
        {
            "type": "action",
            "action": "workflow_validate",
            "args": {
                "spec": {
                    "schema": "workflow.v1",
                    "version": "demo",
                    "nodes": ["research", "training"],
                    "edges": [["research", "training"]],
                }
            },
        },
    )

    assert r["ok"] is True
    assert r["validation"]["execution_order"] == ["research", "training"]


def test_innovation_radar_action(tmp_path: Path) -> None:
    w = tmp_path / "ws"
    w.mkdir()

    r = run_action(w, {"type": "action", "action": "innovation_radar", "args": {}})

    assert r["ok"] is True
    assert r["radar"]["schema"] == "innovation_radar.v1"
    assert r["radar"]["innovation_cards"]


def test_research_synthesize_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    (w / "app.py").write_text("employee approval workflow\n", encoding="utf-8")
    run = tmp_path / "run_demo"
    (run / "docs").mkdir(parents=True)
    (run / "solution_manifest.json").write_text(
        '{"schema":"solution_manifest.v1","template":"spring-vue","stack":"Spring Boot + Vue","goal":"employee approval","retrieval_tags":["employee","approval"],"artifact_hints":["README.md"]}',
        encoding="utf-8",
    )
    (run / "docs" / "SOLUTION_BACKUP.md").write_text("employee approval reusable solution", encoding="utf-8")

    r = run_action(
        w,
        {
            "type": "action",
            "action": "research_synthesize",
            "args": {
                "query": "employee approval",
                "top_k": 2,
                "solution_dirs": [str(tmp_path)],
                "use_web": False,
                "use_llm": False,
            },
        },
        limits=lim,
    )

    assert r["ok"] is True
    assert r["action"] == "research_synthesize"
    assert r["solution_hits"][0]["run_id"] == "run_demo"
    assert r["rag_hints"][0]["path"] == "app.py"
    assert r["manifest"]["kind"] == "research_synthesize"


def test_training_prepare_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    learning = tmp_path / "learning"
    learning.mkdir()
    (learning / "training_examples.jsonl").write_text(
        '{"example_id":"ex","task_type":"qa","instruction":"根据证据回答。","input":"问题","output":"这是一个足够长的训练回答。","citations":[{"path":"README.md"}]}\n',
        encoding="utf-8",
    )

    r = run_action(
        w,
        {
            "type": "action",
            "action": "training_prepare",
            "args": {
                "output_dir": str(tmp_path / "training_out"),
                "learning_dirs": [str(learning)],
                "dataset_format": "messages",
                "eval_ratio": 0.0,
                "min_chars": 10,
                "include_protocol_examples": False,
            },
        },
        limits=lim,
    )

    assert r["ok"] is True
    assert r["action"] == "training_prepare"
    assert r["total_examples"] == 1
    assert Path(r["files"]["train"]).exists()
    assert Path(r["files"]["training_plan"]).exists()
    assert Path(r["files"]["run_manifest"]).exists()


def test_backup_model_train_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = tmp_path / "ws"
    w.mkdir()
    training = tmp_path / "training"
    training.mkdir()
    (training / "train.jsonl").write_text('{"messages":[]}\n', encoding="utf-8")
    (training / "eval.jsonl").write_text('{"messages":[]}\n', encoding="utf-8")
    (training / "training_plan.json").write_text('{"base_model":"demo/base","dataset_format":"messages"}', encoding="utf-8")
    (training / "sample_quality_report.json").write_text('{"overall_score":8.0,"grade":"excellent"}', encoding="utf-8")
    (training / "governance_report.json").write_text('{"grade":"good","metrics":{"secret_scan":{"status":"ok"}}}', encoding="utf-8")
    monkeypatch.setattr(
        "agent.chains.model_training.detect_training_environment",
        lambda: {
            "schema": "backup_training_environment.v1",
            "packages": {"torch": True, "transformers": True, "datasets": False, "peft": False, "trl": False},
            "missing_packages": ["datasets", "peft", "trl"],
            "torch_version": "2.x",
            "cuda_available": False,
            "cuda_device_count": 0,
            "ready": False,
        },
    )

    r = run_action(
        w,
        {
            "type": "action",
            "action": "backup_model_train",
            "args": {
                "training_dir": str(training),
                "output_dir": str(tmp_path / "backup"),
                "min_train_examples": 1,
            },
        },
    )

    assert r["ok"] is False
    assert r["action"] == "backup_model_train"
    assert r["status"] == "blocked_environment"


def test_training_server_preflight_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w = tmp_path / "ws"
    w.mkdir()
    monkeypatch.setattr(
        executor_mod,
        "run_server_resource_preflight",
        lambda policy: {
            "schema": "training_server_preflight.v1",
            "policy": policy,
            "admission": {"admitted": True, "blockers": []},
        },
    )

    r = run_action(w, {"type": "action", "action": "training_server_preflight", "args": {}})

    assert r["ok"] is True
    assert r["preflight"]["admission"]["admitted"] is True


def test_github_crawl_profile_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "README.md").write_text("# Demo\n\nFlask API", encoding="utf-8")
    (repo / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (repo / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8")
    (repo / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    r = run_action(
        w,
        {
            "type": "action",
            "action": "github_crawl_profile",
            "args": {
                "query": "flask api",
                "output_dir": str(tmp_path / "crawl"),
                "local_repos": [str(repo)],
                "repo_limit": 1,
                "min_stars": 0,
                "quality_threshold": 0.0,
            },
        },
        limits=lim,
    )

    assert r["ok"] is True
    assert r["action"] == "github_crawl_profile"
    assert r["profiles"][0]["architecture"]["shape"] == "backend"
    assert Path(r["files"]["profiles"]).exists()
    assert Path(r["files"]["run_manifest"]).exists()
