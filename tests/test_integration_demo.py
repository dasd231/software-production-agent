"""端到端：Scripted 脑 + 主循环（需 flask）。"""

from pathlib import Path

import pytest

pytest.importorskip("flask")

from dataclasses import replace

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import ScriptedDemoBrain


def test_demo_loop_produces_app_and_finishes(tmp_path: Path) -> None:
    ws = tmp_path / "demo_ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(
        AppConfig.from_env(),
        session_log_jsonl=False,
        event_log=False,
        max_agent_iterations=24,
    )
    brain = ScriptedDemoBrain(ws)
    st = run_agent_loop("demo goal", ws, prompts, brain, config=cfg, resume=False)
    assert (ws / "app.py").exists()
    assert st.progress.startswith("finished:")
