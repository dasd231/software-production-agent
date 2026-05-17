"""Dry-run reports for workflow specs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.chains.registry import get_chain
from agent.workflows.spec import validate_workflow_spec


EXPECTED_OUTPUTS: dict[str, list[str]] = {
    "context": ["context_digest", "rag_observability"],
    "intent_compile": ["workflow.v1", "workflow_validation.v1", "workflow_dry_run.v1", "resource_suggestions"],
    "workflow_dry_run": ["execution_order", "permissions", "preflight_gates", "expected_outputs"],
    "research": ["answer", "solution_hits", "rag_hints", "evidence_policy", "evaluation"],
    "training": ["dataset.jsonl", "train.jsonl", "eval.jsonl", "governance_report.json", "run_manifest.json"],
    "github_crawler": ["repo_profiles.json", "solutions/", "evaluation_report.json", "run_manifest.json"],
    "solution_publish": ["solution_manifest.json", "docs/SOLUTION_BACKUP.md", "run_manifest.json"],
    "evidence_ledger": ["evidence_ledger.json"],
}


def _node_report(node: dict[str, Any]) -> dict[str, Any]:
    chain = str(node.get("chain", ""))
    definition = get_chain(chain)
    if not definition:
        return {"id": node.get("id"), "chain": chain, "ok": False, "risks": ["unknown_chain"]}
    risks: list[str] = []
    if definition.network_allowed:
        risks.append("network_access")
    if definition.writes_files:
        risks.append("file_writes")
    return {
        "id": node.get("id"),
        "chain": definition.name,
        "action": definition.action,
        "ok": True,
        "permissions": list(definition.permissions),
        "network_allowed": definition.network_allowed,
        "writes_files": definition.writes_files,
        "cost_level": definition.cost_level,
        "timeout_s": definition.default_timeout_s,
        "expected_outputs": EXPECTED_OUTPUTS.get(definition.name, []),
        "risks": risks,
    }


def dry_run_workflow(spec: dict[str, Any], workspace: Path) -> dict[str, Any]:
    validation = validate_workflow_spec(spec)
    nodes = validation.get("nodes") if isinstance(validation.get("nodes"), list) else []
    node_reports = [_node_report(node) for node in nodes]
    return {
        "schema": "workflow_dry_run.v1",
        "workspace": str(workspace.resolve()),
        "ok": bool(validation.get("ok")),
        "validation": validation,
        "execution_order": validation.get("execution_order", []),
        "nodes": node_reports,
        "permissions": validation.get("permissions", []),
        "network_required": bool(validation.get("network_required")),
        "writes_files": bool(validation.get("writes_files")),
        "approval_required": bool(validation.get("network_required") or validation.get("writes_files")),
        "preflight_gates": [
            "protocol_validation",
            "workspace_path_guard",
            "permission_check",
            "evidence_capture",
            "evaluation_report",
        ],
    }
