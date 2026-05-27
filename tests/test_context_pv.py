from __future__ import annotations

from pathlib import Path

from agent.context_pv import ContextPVPolicy, plan_context_pv, render_context_pv_bundle
from agent.context_pv.slicer import estimate_tokens, slice_context_text
from agent.context_pv.transaction import verify_slice_checksums
from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded


def _long_context() -> str:
    prose = "This project explains long context routing, storage lifecycle, metrics, and recovery. " * 18
    code = "\n".join(
        [
            "```python",
            "class ContextLoader:",
            "    def load_slice(self, slice_id: str) -> str:",
            "        return slice_id",
            "```",
        ]
    )
    metrics = "| metric | meaning |\n| --- | --- |\n| p95_load_ms | slice loading latency |"
    return f"# Overview\n\n{prose}\n\n{code}\n\n## Evaluation\n\n{metrics}\n\n{prose}"


def test_short_context_stays_single_slice() -> None:
    policy = ContextPVPolicy(single_pv_token_threshold=10_000)
    slices, total = slice_context_text("short architecture summary", policy=policy, manifest_id="m")

    assert len(slices) == 1
    assert total == estimate_tokens("short architecture summary")
    assert slices[0].overlap_left == 0
    assert slices[0].overlap_right == 0
    assert verify_slice_checksums(slices)[slices[0].slice_id] is True


def test_long_context_uses_semantic_slices_overlap_and_routes_code() -> None:
    policy = ContextPVPolicy(
        tenant="demo",
        single_pv_token_threshold=50,
        target_slice_tokens=60,
        max_slice_tokens=90,
        overlap_tokens=8,
        route_top_k=3,
    )
    plan = plan_context_pv(_long_context(), query="How does ContextLoader load_slice code work?", policy=policy)

    assert len(plan.manifest.slices) > 1
    assert any(item.overlap_left > 0 for item in plan.manifest.slices[1:])
    assert any(item.semantic_label == "code" for item in plan.manifest.slices)
    assert plan.manifest.merkle_root
    assert plan.transaction.consistency_mode == "strong_manifest_version"
    assert len(plan.transaction.wal_records) == len(plan.manifest.slices) * 3
    routed_ids = plan.load_plan["required_slice_ids"]
    routed_labels = {item.semantic_label for item in plan.manifest.slices if item.slice_id in routed_ids}
    assert "code" in routed_labels


def test_placement_uses_tiers_replicas_and_global_index() -> None:
    policy = ContextPVPolicy(
        tenant="enterprise",
        single_pv_token_threshold=50,
        target_slice_tokens=50,
        max_slice_tokens=80,
        overlap_tokens=5,
        hot_tier_token_budget=80,
        warm_tier_token_budget=140,
        replica_factor_critical=2,
    )
    plan = plan_context_pv(_long_context() * 2, query="metrics table latency", policy=policy)

    tiers = {item.pv_tier for item in plan.manifest.placements}
    assert "hot" in tiers
    assert tiers <= {"hot", "warm", "cold"}
    assert any(len(item.replica_pvc_names) >= 2 for item in plan.manifest.placements)
    assert plan.manifest.global_index["by_label"]
    assert plan.lifecycle_plan["dynamic_provisioning"]["enabled"] is True
    assert "gpu" in {tier["name"] for tier in plan.cache_plan["tiers"]}
    assert plan.security_plan["quota"]["storage"] == policy.quota_storage_limit


def test_k8s_bundle_contains_storage_pvc_job_policy_and_quota() -> None:
    policy = ContextPVPolicy(single_pv_token_threshold=30, target_slice_tokens=30, max_slice_tokens=60)
    plan = plan_context_pv(_long_context(), query="overview", policy=policy)
    bundle = render_context_pv_bundle(plan)
    kinds = [doc["kind"] for doc in bundle]

    assert "Namespace" in kinds
    assert "ResourceQuota" in kinds
    assert "StorageClass" in kinds
    assert "PersistentVolumeClaim" in kinds
    assert "ConfigMap" in kinds
    assert "Job" in kinds
    assert "NetworkPolicy" in kinds
    loader = next(doc for doc in bundle if doc["kind"] == "Job")
    assert loader["spec"]["template"]["spec"]["initContainers"][0]["name"] == "verify-manifest"
    assert loader["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] is True


def test_context_pv_plan_action_writes_plan_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"context_pv_plan","args":'
        '{"text":"# Overview\\n\\nhello context pv world","query":"overview","output_path":"plans/pv.json"}}'
    )
    direct = run_action(tmp_path, action)
    assert direct["ok"] is True
    assert direct["summary"]["slice_count"] >= 1
    assert (tmp_path / "plans" / "pv.json").exists()

    denied = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    allowed = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"context:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"

