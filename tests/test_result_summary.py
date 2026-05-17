from agent.core.agent_loop import _result_summary


def test_result_summary_for_failed_command() -> None:
    result = {
        "action": "run_command",
        "ok": False,
        "returncode": 1,
        "stderr": "Traceback: boom\nline2",
    }
    s = _result_summary(result)
    assert s["action"] == "run_command"
    assert s["ok"] is False
    assert s["returncode"] == 1
    assert "stderr_head" in s


def test_result_summary_for_finish() -> None:
    s = _result_summary({"action": "finish", "ok": True, "reason": "done"})
    assert s == {"action": "finish", "ok": True, "reason": "done"}


def test_result_summary_for_production_check() -> None:
    s = _result_summary(
        {
            "action": "production_check",
            "ok": False,
            "report": {
                "summary": {"python_files": 2, "compile_failures": 1, "pytest_ran": False},
                "checks": [{"name": "py_compile", "ok": False}],
            },
        }
    )
    assert s["action"] == "production_check"
    assert s["compile_failures"] == 1
    assert s["failed_checks"] == ["py_compile"]
