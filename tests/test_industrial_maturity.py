from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import run_action
from agent.enterprise.maturity import build_industrial_maturity_plan


def test_industrial_maturity_plan_scores_dimensions_and_cto_pack(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "solution_manifest.json").write_text(
        json.dumps({"template": "demo", "retrieval_tags": ["rag"], "quality_score": 8.0}),
        encoding="utf-8",
    )
    (ws / "run_manifest.json").write_text(json.dumps({"kind": "demo", "manifest_id": "m1"}), encoding="utf-8")
    (ws / "evidence_ledger.json").write_text(
        json.dumps({"summary": {"total": 2, "by_type": {"run_manifest": 1}}}),
        encoding="utf-8",
    )

    out = build_industrial_maturity_plan("军工工业级 AI CTO 审查", ws)

    assert out["schema"] == "industrial_maturity_plan.v1"
    assert out["posture"] == "safety-critical-industrial-ai"
    assert out["overall"]["target_level"] == 5
    names = {row["name"] for row in out["dimensions"]}
    assert "model_plane_governance" in names
    assert "multi_agent_execution_control" in names
    assert "security_supply_chain_and_compliance" in names
    assert out["cto_interrogation_pack"]
    assert "no model/workflow/rag release without eval and rollback plan" in out["non_negotiable_gates"]


def test_industrial_maturity_action_dispatches(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    out = run_action(
        ws,
        {
            "type": "action",
            "action": "industrial_maturity_plan",
            "args": {
                "goal": "安全关键工业 AI 平台成熟度",
                "scale": "listed",
                "regulated": True,
            },
        },
    )

    assert out["ok"] is True
    assert out["plan"]["schema"] == "industrial_maturity_plan.v1"
    assert out["plan"]["roadmap"][0]["horizon"] == "0-30 days"
