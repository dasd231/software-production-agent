from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.integrations.embedding import build_integration_embed_plan, list_integration_catalog
from agent.resources.registry import discover_resources


FIGMA_URL = "https://www.figma.com/file/abc123/Product-Design"


def test_integration_catalog_lists_enterprise_surfaces() -> None:
    catalog = list_integration_catalog()

    ids = {row["id"] for row in catalog["integrations"]}
    assert catalog["schema"] == "integration_catalog.v1"
    assert {"figma", "github", "notion"}.issubset(ids)
    assert "action_bridge" in catalog["surfaces"]


def test_figma_embed_plan_contains_sandbox_bridge_and_asset_mapping() -> None:
    plan = build_integration_embed_plan(
        "figma",
        resource_url=FIGMA_URL,
        mode="embed_panel",
        requested_capabilities=("frame_selection", "design_token_handoff"),
    )

    assert plan["schema"] == "integration_embed_plan.v1"
    assert plan["admission"]["embeddable"] is True
    assert plan["surface"]["iframe_url"].startswith("https://www.figma.com/embed")
    assert "https%3A%2F%2Fwww.figma.com%2Ffile%2Fabc123%2FProduct-Design" in plan["surface"]["iframe_url"]
    assert "allow-scripts" in plan["surface"]["sandbox"]
    assert "selection.changed" in plan["bridge_contract"]["child_to_parent"]
    assert {"external": "design_tokens", "internal": "frontend_style_spec"} in plan["artifact_mapping"]["mappings"]


def test_embed_plan_rejects_unsafe_or_wrong_origin_urls() -> None:
    unsafe = build_integration_embed_plan("figma", resource_url="javascript:alert(1)", mode="embed_panel")
    wrong_origin = build_integration_embed_plan(
        "figma",
        resource_url="https://evil.example/file/abc",
        mode="embed_panel",
    )

    assert unsafe["admission"]["embeddable"] is False
    assert "blocked_url_scheme" in unsafe["admission"]["reasons"]
    assert wrong_origin["admission"]["embeddable"] is False
    assert "origin_not_allowed" in wrong_origin["admission"]["reasons"]


def test_resource_registry_exposes_integrations(tmp_path: Path) -> None:
    registry = discover_resources(tmp_path, type_filter="integration")

    ids = {row["id"] for row in registry["resources"]}
    assert registry["summary"]["by_type"]["integration"] >= 5
    assert "integration:figma" in ids


def test_integration_actions_dispatch(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    catalog = run_action(workspace, {"type": "action", "action": "integration_catalog", "args": {}})
    plan = run_action(
        workspace,
        {
            "type": "action",
            "action": "integration_embed_plan",
            "args": {
                "integration_id": "figma",
                "resource_url": FIGMA_URL,
                "mode": "embed_panel",
                "requested_capabilities": ["frame_selection"],
            },
        },
    )

    assert catalog["ok"] is True
    assert catalog["catalog"]["schema"] == "integration_catalog.v1"
    assert plan["ok"] is True
    assert plan["plan"]["integration"]["id"] == "figma"
