from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def demo_middle_traces() -> list[dict[str, Any]]:
    return [
        {
            "trace_id": "middle_safe_shortcut_001",
            "decision": {"confidence": 0.93, "margin": 0.41, "risk_signal": "low", "should_run_expensive_rules": False},
            "ranked_candidates": [{"id": "slot_rbac"}, {"id": "slot_audit"}, {"id": "slot_tests"}],
            "coverage_report": {"must_have_coverage_rate": 1.0, "has_missing_must_have": False},
            "guard_report": {"ok": True, "violations": []},
            "labels": {"final_accepted": True, "shortcut_success": True, "latency_saved_ms": 420, "quality_delta": 0.08},
        },
        {
            "trace_id": "middle_guard_block_002",
            "decision": {"confidence": 0.51, "margin": 0.03, "risk_signal": "high", "should_run_expensive_rules": True},
            "ranked_candidates": [{"id": "slot_auth"}],
            "coverage_report": {"must_have_coverage_rate": 0.5, "has_missing_must_have": True},
            "guard_report": {"ok": False, "violations": [{"code": "UNAUTHORIZED_DEPLOY"}]},
            "patch_proposal": {"risk_level": "high"},
            "labels": {"final_accepted": False, "shortcut_success": False, "quality_delta": -0.4},
        },
        {
            "trace_id": "middle_human_override_003",
            "decision": {"confidence": 0.74, "margin": 0.18, "risk_signal": "medium", "should_run_expensive_rules": True},
            "ranked_candidates": [{"id": "slot_payment"}, {"id": "slot_idempotency"}],
            "coverage_report": {"must_have_coverage_rate": 0.75, "has_missing_must_have": False},
            "guard_report": {"ok": True, "violations": []},
            "labels": {"human_override": True, "final_accepted": True, "quality_delta": 0.0},
        },
    ]


def demo_github_rankings() -> list[dict[str, Any]]:
    return [
        {
            "repo": "example/spring-boot-rbac-saas",
            "routes": ["train_now"],
            "scores": {
                "lexical_relevance": 8.8,
                "repo_quality": 9.0,
                "freshness": 7.5,
                "governance": 9.2,
                "novelty": 6.8,
                "downstream_utility": 8.7,
                "architecture_depth": 8.4,
                "security_signal": 0.95,
            },
            "checks": {"has_tests": True, "has_ci": True, "license_ok": True, "secret_scan_passed": True},
        },
        {
            "repo": "example/no-license-random-demo",
            "routes": ["quarantine"],
            "scores": {
                "lexical_relevance": 7.0,
                "repo_quality": 3.0,
                "freshness": 6.0,
                "governance": 0.0,
                "novelty": 4.0,
                "downstream_utility": 2.0,
                "architecture_depth": 2.5,
                "security_signal": 0.2,
            },
            "checks": {"has_tests": False, "has_ci": False, "license_ok": False, "secret_scan_passed": True},
        },
        {
            "repo": "example/high-quality-seckill-system",
            "routes": ["distill_pool"],
            "scores": {
                "lexical_relevance": 8.2,
                "repo_quality": 8.4,
                "freshness": 8.0,
                "governance": 8.5,
                "novelty": 7.2,
                "downstream_utility": 8.1,
                "architecture_depth": 8.0,
                "security_signal": 0.9,
            },
            "checks": {"has_tests": True, "has_ci": True, "license_ok": True, "secret_scan_passed": True},
        },
    ]


def write_demo_local_training_data(output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    middle_path = output_dir / "demo_middle_traces.jsonl"
    github_path = output_dir / "demo_github_rankings.jsonl"
    for path, rows in ((middle_path, demo_middle_traces()), (github_path, demo_github_rankings())):
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"middle_trace_path": str(middle_path), "github_ranking_path": str(github_path)}
