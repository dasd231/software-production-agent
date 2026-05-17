from pathlib import Path

from agent.config import AppConfig
from agent.core.planner import plan_heuristic
from agent.memory.project_state import ProjectState


def test_planner_fixing_when_errors(tmp_path: Path) -> None:
    st = ProjectState(errors=[{"source": "x", "message": "m", "stderr": ""}])
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "fixing"


def test_planner_coding_when_empty(tmp_path: Path) -> None:
    st = ProjectState()
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "coding"


def test_planner_investigate_after_repeated_failures(tmp_path: Path) -> None:
    st = ProjectState(errors=[{"source": "x", "message": "m", "stderr": ""}], counters={"command_failures": 3})
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "investigate"


def test_planner_investigate_uses_handoff_recommendations(tmp_path: Path) -> None:
    st = ProjectState(
        errors=[{"source": "x", "message": "m", "stderr": ""}],
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
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "investigate"
    assert p["meta"]["recommended_next_actions"][0] == "verify_dependencies_and_import_paths"
    assert p["tasks"][0].startswith("按建议执行:")


def test_planner_moves_review_to_qa(tmp_path: Path) -> None:
    st = ProjectState(current_stage="review", quality={"review_score": 8.0, "health_score": None, "wtf_likelihood": 0})
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "qa"


def test_planner_moves_qa_to_ship(tmp_path: Path) -> None:
    st = ProjectState(current_stage="qa", quality={"review_score": 8.0, "health_score": 7.2, "wtf_likelihood": 0})
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "ship"


def test_planner_coding_tasks_include_context_hints(tmp_path: Path) -> None:
    st = ProjectState(
        structure={
            "skill_hints": ["api-design"],
            "rag_hints": ["flask hello snippet"],
        }
    )
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "coding"
    joined = "\n".join(p["tasks"])
    assert "rag_hints" in joined
    assert "skill_hints" in joined


def test_planner_fixing_tasks_include_mcp_debug_hints(tmp_path: Path) -> None:
    st = ProjectState(
        errors=[{"source": "x", "message": "m", "stderr": ""}],
        structure={"mcp_capabilities": [{"tool": "workspace.search"}, {"tool": "workspace.read"}]},
    )
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "fixing"
    joined = "\n".join(p["tasks"])
    assert "mcp 工具" in joined
    assert "workspace.search" in joined


def test_planner_investigate_tasks_append_context_hints(tmp_path: Path) -> None:
    st = ProjectState(
        errors=[{"source": "x", "message": "m", "stderr": ""}],
        counters={"command_failures": 3},
        structure={
            "investigate_handoff": {"recommended_next_actions": ["collect_minimal_repro"]},
            "skill_hints": ["debugging"],
            "rag_hints": ["error trace snippet"],
            "mcp_capabilities": [{"tool": "workspace.search"}],
        },
    )
    p = plan_heuristic("goal", st, tmp_path)
    assert p["stage"] == "investigate"
    joined = "\n".join(p["tasks"])
    assert "按建议执行: collect_minimal_repro" in joined
    assert "rag_hints" in joined
    assert "mcp 工具" in joined
