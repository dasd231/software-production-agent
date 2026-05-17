from pathlib import Path

import pytest

from agent.core.executor import ExecutionLimits, ExecutorError, run_action
from agent.policies.loader import merged_forbidden_substrings


def test_git_status_action(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    r = run_action(w, {"type": "action", "action": "git_status", "args": {}}, limits=lim)
    assert r["ok"] is True
    assert "content" in r


def test_git_init_idempotent(tmp_path: Path) -> None:
    lim = ExecutionLimits()
    w = tmp_path / "ws"
    w.mkdir()
    r1 = run_action(w, {"type": "action", "action": "git_init", "args": {}}, limits=lim)
    if not r1.get("ok"):
        pytest.skip("git CLI not available or init failed")
    r2 = run_action(w, {"type": "action", "action": "git_init", "args": {}}, limits=lim)
    assert r2["ok"] is True
    assert r2.get("status") == "already_git_repo"


def test_extra_policy_blocks_command(tmp_path: Path) -> None:
    merged_forbidden_substrings.cache_clear()
    fixture = Path(__file__).resolve().parent / "fixtures" / "extra_policy.json"
    lim = ExecutionLimits(policy_extra_path=fixture)
    w = tmp_path / "ws"
    w.mkdir()
    with pytest.raises(ExecutorError, match="blocked"):
        run_action(
            w,
            {
                "type": "action",
                "action": "run_command",
                "args": {"command": 'echo __agent_policy_probe_block__'},
            },
            limits=lim,
        )
    merged_forbidden_substrings.cache_clear()


def test_git_status_rejects_extra_args() -> None:
    from agent.core.protocol import ProtocolError, parse_and_validate_action_line

    with pytest.raises(ProtocolError):
        parse_and_validate_action_line(
            '{"type":"action","action":"git_status","args":{"x":1}}'
        )
