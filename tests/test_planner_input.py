from agent.core.planner import _planner_input
from agent.memory.project_state import ProjectState


def test_planner_input_includes_priority_guidance_when_failures_high() -> None:
    st = ProjectState(
        counters={"command_failures": 3},
        structure={
            "investigate_handoff": {
                "recommended_next_actions": [
                    "verify_dependencies_and_import_paths",
                    "run_pip_show_or_pip_list_for_missing_module",
                ]
            }
        },
    )
    payload = _planner_input("goal", st)
    assert "priority_guidance" in payload
    assert payload["priority_guidance"]["mode"] == "investigate"


def test_planner_input_omits_priority_guidance_when_not_needed() -> None:
    st = ProjectState(counters={"command_failures": 1}, structure={})
    payload = _planner_input("goal", st)
    assert "priority_guidance" not in payload


def test_planner_input_contains_context_digest() -> None:
    st = ProjectState(
        structure={
            "skill_hints": ["api-design", "debugging"],
            "rag_hints": ["snippet-a", "snippet-b"],
            "mcp_capabilities": [{"tool": "workspace.search"}, {"tool": "workspace.read"}],
        }
    )
    payload = _planner_input("goal", st)
    digest = payload["context_digest"]
    assert digest["skill_hints"][0] == "api-design"
    assert digest["rag_hints"][0] == "snippet-a"
    assert digest["mcp_capabilities"][0]["tool"] == "workspace.search"
    assert digest["summary"]["mcp_capabilities"]["included"] == 2


def test_planner_input_compacts_structured_rag_hints() -> None:
    st = ProjectState(
        structure={
            "rag_hints": [
                {
                    "path": "server.py",
                    "line_start": 10,
                    "line_end": 12,
                    "score": 8,
                    "overlap_tokens": ["handler", "error"],
                    "line_overlap_tokens": ["handler"],
                    "size_bytes": 88,
                    "preview": "def handler():\n    raise RuntimeError()",
                }
            ],
        }
    )
    payload = _planner_input("goal", st)
    hint = payload["context_digest"]["rag_hints"][0]
    assert hint["path"] == "server.py"
    assert hint["line_start"] == 10
    assert hint["overlap_tokens"] == ["handler", "error"]
    assert hint["line_overlap_tokens"] == ["handler"]
    assert hint["size_bytes"] == 88


def test_planner_input_includes_debug_capability_hints_on_repeated_failures() -> None:
    st = ProjectState(
        counters={"command_failures": 3},
        structure={
            "mcp_capabilities": [{"tool": "workspace.search"}, {"tool": "git.status"}],
            "investigate_handoff": {"recommended_next_actions": ["collect_minimal_repro"]},
        },
    )
    payload = _planner_input("goal", st)
    assert payload["debug_capability_hints"] == ["workspace.search", "git.status"]
