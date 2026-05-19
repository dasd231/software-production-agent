"""Action governance metadata and preflight checks.

This layer complements protocol validation:

- ``protocol.py`` answers "is this a well-formed allowed action?"
- ``governance.py`` answers "may this run execute that action now?"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionGovernanceSpec:
    permissions: tuple[str, ...] = ()
    risk_level: str = "low"
    requires_confirmation: bool = False
    idempotency: str = "not_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "permissions": list(self.permissions),
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "idempotency": self.idempotency,
        }


_LOW_READ = ActionGovernanceSpec(("workspace:read",), "low")


ACTION_GOVERNANCE: dict[str, ActionGovernanceSpec] = {
    "write_file": ActionGovernanceSpec(("workspace:write",), "medium"),
    "read_file": _LOW_READ,
    "run_command": ActionGovernanceSpec(("command:run",), "high"),
    "list_files": _LOW_READ,
    "finish": ActionGovernanceSpec((), "low"),
    "git_status": ActionGovernanceSpec(("repo:read",), "low"),
    "git_init": ActionGovernanceSpec(("repo:write",), "high", requires_confirmation=True),
    "workspace_index": _LOW_READ,
    "mcp_call": ActionGovernanceSpec(("mcp:call",), "medium"),
    "mcp_capabilities": ActionGovernanceSpec(("mcp:read",), "low"),
    "production_check": ActionGovernanceSpec(("workspace:read", "command:run"), "medium"),
    "web_search": ActionGovernanceSpec(("network:read",), "medium"),
    "chain_registry": ActionGovernanceSpec(("registry:read",), "low"),
    "resource_registry": ActionGovernanceSpec(("registry:read",), "low"),
    "integration_catalog": ActionGovernanceSpec(("integration:read",), "low"),
    "integration_embed_plan": ActionGovernanceSpec(("integration:read",), "low"),
    "model_runtime_status": ActionGovernanceSpec(("model:read",), "low"),
    "model_admission_status": ActionGovernanceSpec(("model:read",), "low"),
    "model_admission_acquire": ActionGovernanceSpec(("model:admit",), "medium", idempotency="supported"),
    "model_admission_release": ActionGovernanceSpec(("model:admit",), "medium"),
    "model_admission_renew": ActionGovernanceSpec(("model:admit",), "medium"),
    "model_route_plan": ActionGovernanceSpec(("model:route",), "low"),
    "software_middle_model_plan": ActionGovernanceSpec(("model:read",), "low"),
    "software_middle_model_decide": ActionGovernanceSpec(("model:route",), "low"),
    "enterprise_stack_plan": ActionGovernanceSpec(("workspace:read",), "low"),
    "industrial_maturity_plan": ActionGovernanceSpec(("workspace:read",), "low"),
    "enterprise_readiness_check": ActionGovernanceSpec(("workspace:read",), "low"),
    "workflow_validate": ActionGovernanceSpec(("workflow:read",), "low"),
    "innovation_radar": ActionGovernanceSpec(("workspace:read", "registry:read"), "low"),
    "intent_compile": ActionGovernanceSpec(("workspace:read", "workflow:read"), "low"),
    "workflow_dry_run": ActionGovernanceSpec(("workspace:read", "workflow:read"), "low"),
    "evidence_ledger": ActionGovernanceSpec(("workspace:read", "evidence:write"), "medium"),
    "research_feedback_report": ActionGovernanceSpec(("workspace:read",), "low"),
    "solution_publish": ActionGovernanceSpec(
        ("workspace:read", "solution:write"),
        "high",
        requires_confirmation=True,
    ),
    "research_synthesize": ActionGovernanceSpec(("workspace:read", "solution:read", "evidence:write"), "medium"),
    "training_prepare": ActionGovernanceSpec(
        ("dataset:write",),
        "high",
        requires_confirmation=True,
    ),
    "teacher_prompt_batch_build": ActionGovernanceSpec(("dataset:read",), "low"),
    "teacher_execution_plan_build": ActionGovernanceSpec(("model:read",), "low"),
    "teacher_execution_run": ActionGovernanceSpec(
        ("model:call",),
        "high",
        requires_confirmation=True,
    ),
    "teacher_output_review_build": ActionGovernanceSpec(("dataset:read",), "low"),
    "distillation_export_build": ActionGovernanceSpec(
        ("dataset:write",),
        "high",
        requires_confirmation=True,
    ),
    "first_training_round_plan": ActionGovernanceSpec(("dataset:read",), "low"),
    "training_server_preflight": ActionGovernanceSpec(("model:read",), "low"),
    "github_corpus_program_plan": ActionGovernanceSpec(("workspace:read",), "low"),
    "github_query_plan_build": ActionGovernanceSpec(("workspace:read",), "low"),
    "github_candidate_rank": ActionGovernanceSpec(("workspace:read",), "low"),
    "corpus_feedback_plan": ActionGovernanceSpec(("workspace:read",), "low"),
    "backup_model_train": ActionGovernanceSpec(
        ("dataset:read", "model:write"),
        "high",
        requires_confirmation=True,
    ),
    "github_crawl_profile": ActionGovernanceSpec(
        ("repo:read", "solution:write"),
        "high",
        requires_confirmation=True,
    ),
}


def action_governance(name: str) -> ActionGovernanceSpec:
    return ACTION_GOVERNANCE.get(name, ActionGovernanceSpec(("agent:execute",), "medium"))


def _permission_allowed(required: str, granted: frozenset[str]) -> bool:
    if "*" in granted or required in granted:
        return True
    namespace = required.split(":", 1)[0]
    return f"{namespace}:*" in granted


def build_preflight_report(
    action_name: str,
    args: dict[str, Any],
    *,
    granted_permissions: frozenset[str],
    confirmed_actions: frozenset[str],
) -> dict[str, Any]:
    """Return an auditable, side-effect-free execution preflight decision."""

    spec = action_governance(action_name)
    missing = [perm for perm in spec.permissions if not _permission_allowed(perm, granted_permissions)]
    confirmation_granted = not spec.requires_confirmation or action_name in confirmed_actions
    idempotency_present = bool(str(args.get("idempotency_key", "") or "").strip())

    if missing:
        status = "permission_denied"
        allowed = False
        error_code = "PERMISSION_DENIED"
    elif not confirmation_granted:
        status = "confirmation_required"
        allowed = False
        error_code = "CONFIRMATION_REQUIRED"
    else:
        status = "allowed"
        allowed = True
        error_code = ""

    return {
        "allowed": allowed,
        "status": status,
        "error_code": error_code,
        "risk_level": spec.risk_level,
        "required_permissions": list(spec.permissions),
        "missing_permissions": missing,
        "requires_confirmation": spec.requires_confirmation,
        "confirmation_granted": confirmation_granted,
        "idempotency": {
            "policy": spec.idempotency,
            "present": idempotency_present,
        },
    }
