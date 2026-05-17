import json

from agent.core.feedback import analyze_exec_result


def test_analyze_exec_result_production_check_failure_is_compact() -> None:
    msg = analyze_exec_result(
        {
            "action": "production_check",
            "ok": False,
            "report": {
                "summary": {"python_files": 2, "compile_failures": 1},
                "checks": [{"name": "py_compile", "ok": False, "failures": [{"path": "bad.py"}]}],
            },
        }
    )
    assert msg is not None
    data = json.loads(msg)
    assert data["action"] == "production_check"
    assert data["failed_checks"][0]["name"] == "py_compile"
