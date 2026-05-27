from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.sandbox.k8s_job import K8sSandboxSpec, render_sandbox_bundle, render_sandbox_job_manifest
from agent.supervisor.policy import review_action


def test_supervisor_allows_safe_command_but_records_audit(tmp_path: Path) -> None:
    decision = review_action(
        "run_command",
        {"command": "python -V", "timeout": 30},
        workspace=tmp_path,
        granted_permissions=frozenset({"*"}),
    )

    assert decision.allowed is True
    assert decision.status == "allowed"
    assert decision.risk_level == "high"  # run_command governance is high risk even when allowed
    assert decision.audit_events


def test_supervisor_denies_destructive_command(tmp_path: Path) -> None:
    decision = review_action(
        "run_command",
        {"command": "rm -rf /"},
        workspace=tmp_path,
        granted_permissions=frozenset({"*"}),
    )

    assert decision.allowed is False
    assert decision.status == "denied"
    assert decision.risk_level == "critical"
    assert "command denied" in decision.reason


def test_guarded_executor_embeds_supervisor_report_and_blocks_supervisor_denial(tmp_path: Path) -> None:
    result = run_action_guarded(
        tmp_path,
        {"type": "action", "action": "run_command", "args": {"command": "rm -rf /"}},
        limits=ExecutionLimits(granted_permissions=frozenset({"*"})),
    )

    assert result["ok"] is False
    assert result["error_code"] == "SUPERVISOR_DENIED"
    assert result["preflight"]["supervisor"]["status"] == "denied"


def test_supervisor_recommends_k8s_sandbox_for_training_command(tmp_path: Path) -> None:
    decision = review_action(
        "run_command",
        {"command": "python train_model.py", "timeout": 600},
        workspace=tmp_path,
        granted_permissions=frozenset({"*"}),
    )

    assert decision.allowed is True
    assert decision.sandbox_recommended is True
    assert any("k8s sandbox" in warning for warning in decision.warnings)


def test_supervisor_requires_k8s_sandbox_when_requested(tmp_path: Path) -> None:
    result = run_action_guarded(
        tmp_path,
        {"type": "action", "action": "run_command", "args": {"command": "python train_model.py", "sandbox": "k8s"}},
        limits=ExecutionLimits(granted_permissions=frozenset({"*"})),
    )

    assert result["ok"] is False
    assert result["error_code"] == "SUPERVISOR_SANDBOX_REQUIRED"
    assert result["recommended_action"] == "dispatch_to_k8s_sandbox"


def test_k8s_sandbox_job_manifest_has_hardening_defaults() -> None:
    manifest = render_sandbox_job_manifest(
        {"type": "action", "action": "run_command", "args": {"command": "python train_model.py"}},
        spec=K8sSandboxSpec(namespace="lab-sandbox", active_deadline_seconds=120),
    )

    pod_spec = manifest["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]
    assert manifest["kind"] == "Job"
    assert manifest["metadata"]["namespace"] == "lab-sandbox"
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert manifest["spec"]["activeDeadlineSeconds"] == 120


def test_k8s_sandbox_bundle_adds_default_deny_network_policy() -> None:
    bundle = render_sandbox_bundle(
        {"type": "action", "action": "run_command", "args": {"command": "python -V"}},
        spec=K8sSandboxSpec(namespace="lab-sandbox", network="none"),
    )

    assert [doc["kind"] for doc in bundle] == ["Job", "NetworkPolicy"]
    assert bundle[1]["spec"]["egress"] == []


def test_k8s_sandbox_plan_action_renders_manifest_and_writes_file(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"k8s_sandbox_plan","args":'
        '{"command":"python train_model.py","namespace":"lab-sandbox","output_path":"sandbox/job.json"}}'
    )
    result = run_action(tmp_path, action)

    assert result["ok"] is True
    assert result["action"] == "k8s_sandbox_plan"
    assert result["sandbox"]["namespace"] == "lab-sandbox"
    assert result["manifest"][0]["kind"] == "Job"
    assert result["manifest"][1]["kind"] == "NetworkPolicy"
    assert (tmp_path / "sandbox" / "job.json").exists()


def test_guarded_k8s_sandbox_plan_uses_supervisor_permissions(tmp_path: Path) -> None:
    denied = run_action_guarded(
        tmp_path,
        {"type": "action", "action": "k8s_sandbox_plan", "args": {"command": "python -V"}},
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    allowed = run_action_guarded(
        tmp_path,
        {"type": "action", "action": "k8s_sandbox_plan", "args": {"command": "python -V"}},
        limits=ExecutionLimits(granted_permissions=frozenset({"sandbox:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"


def test_k8s_sandbox_plan_rejects_output_path_escape(tmp_path: Path) -> None:
    result = run_action_guarded(
        tmp_path,
        {
            "type": "action",
            "action": "k8s_sandbox_plan",
            "args": {"command": "python -V", "output_path": "../outside.json"},
        },
        limits=ExecutionLimits(granted_permissions=frozenset({"sandbox:plan", "workspace:write"})),
    )

    assert result["ok"] is False
    assert result["error_code"] == "SUPERVISOR_DENIED"
    assert "path escapes workspace" in result["error"]
