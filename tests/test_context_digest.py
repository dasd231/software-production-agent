from agent.context.digest import build_context_digest


def test_context_digest_compacts_rag_hint_fields() -> None:
    digest = build_context_digest(
        {
            "skill_hints": ["a", "b", "c", "d"],
            "rag_hints": [
                {
                    "path": "app.py",
                    "line_start": 2,
                    "line_end": 5,
                    "score": 7,
                    "overlap_tokens": list(range(12)),
                    "line_overlap_tokens": ["handler"],
                    "size_bytes": 512,
                    "preview": "x" * 300,
                    "truncated": True,
                },
                {"path": "model.py", "preview": "class Model: pass"},
                {"path": "views.py", "preview": "def view(): pass"},
                {"path": "extra.py", "preview": "omitted"},
            ],
            "mcp_capabilities": [{"tool": "workspace.search"}] * 6,
            "decision_policy": {
                "policy_version": "heuristic-v1",
                "strategy": "verify",
                "selected_action": "production_check",
                "selected_score": 0.9,
                "reason": "verification is best",
                "features": {
                    "stage": "qa",
                    "progress": "run_ok",
                    "recent_error_count": 0,
                    "command_failures": 0,
                    "rag_hit_count": 4,
                    "tests_count": 2,
                    "mcp_tool_count": 5,
                    "last_command_failed": False,
                },
                "candidate_actions": [{"action": "production_check", "score": 0.9, "reason": "verify"}],
            },
        }
    )

    hint = digest["rag_hints"][0]
    assert digest["skill_hints"] == ["a", "b", "c"]
    assert len(digest["rag_hints"]) == 3
    assert len(digest["mcp_capabilities"]) == 5
    assert digest["summary"]["skill_hints"] == {"total": 4, "included": 3, "omitted": 1}
    assert digest["summary"]["rag_hints"] == {"total": 4, "included": 3, "omitted": 1}
    assert digest["summary"]["mcp_capabilities"] == {"total": 6, "included": 5, "omitted": 1}
    assert digest["summary"]["decision_policy"] == {"total": 1, "included": 1, "omitted": 0}
    assert digest["summary"]["rag_truncated"] == 1
    assert digest["decision_policy"]["strategy"] == "verify"
    assert digest["decision_policy"]["selected_action"] == "production_check"
    assert digest["decision_policy"]["features"]["tests_count"] == 2
    assert hint["path"] == "app.py"
    assert hint["line_start"] == 2
    assert hint["line_end"] == 5
    assert hint["score"] == 7
    assert hint["overlap_tokens"] == [str(x) for x in range(8)]
    assert hint["line_overlap_tokens"] == ["handler"]
    assert hint["size_bytes"] == 512
    assert len(hint["preview"]) == 260
    assert hint["truncated"] is True


def test_context_digest_tolerates_dirty_rag_hint_values() -> None:
    digest = build_context_digest(
        {
            "skill_hints": "not-a-list",
            "rag_hints": [
                {
                    "path": None,
                    "line_start": "bad",
                    "line_end": -5,
                    "score": None,
                    "overlap_tokens": "flask",
                    "line_overlap_tokens": {"x": 1},
                    "size_bytes": "NaN",
                    "preview": None,
                }
            ],
            "mcp_capabilities": "not-a-list",
        }
    )

    hint = digest["rag_hints"][0]
    assert digest["skill_hints"] == []
    assert digest["mcp_capabilities"] == []
    assert digest["summary"]["skill_hints"] == {"total": 0, "included": 0, "omitted": 0}
    assert digest["summary"]["rag_hints"] == {"total": 1, "included": 1, "omitted": 0}
    assert digest["summary"]["mcp_capabilities"] == {"total": 0, "included": 0, "omitted": 0}
    assert digest["summary"]["rag_truncated"] == 0
    assert hint["path"] == "None"
    assert hint["line_start"] == 0
    assert hint["line_end"] == 0
    assert hint["score"] == 0
    assert hint["overlap_tokens"] == []
    assert hint["line_overlap_tokens"] == []
    assert hint["size_bytes"] == 0
    assert hint["preview"] == "None"
