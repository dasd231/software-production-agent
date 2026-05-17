from pathlib import Path

from agent.runtime.production_check import run_production_checks


def test_run_production_checks_runs_pytest_when_targets_exist(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    tests = ws / "tests"
    tests.mkdir(parents=True)
    (ws / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tests / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    report = run_production_checks(ws, include_pytest=True, timeout=30.0)
    assert report["ok"] is True
    assert report["summary"]["pytest_ran"] is True


def test_run_production_checks_reports_pytest_failure(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    tests = ws / "tests"
    tests.mkdir(parents=True)
    (tests / "test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    report = run_production_checks(ws, include_pytest=True, timeout=30.0)
    assert report["ok"] is False
    pytest_check = [x for x in report["checks"] if x["name"] == "pytest"][0]
    assert pytest_check["returncode"] != 0
