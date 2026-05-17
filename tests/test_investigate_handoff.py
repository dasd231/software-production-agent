from agent.core.agent_loop import _build_investigate_handoff
from agent.memory.project_state import ProjectState


def test_investigate_handoff_import_error_recommendations() -> None:
    st = ProjectState(
        errors=[
            {
                "source": "executor",
                "message": "ModuleNotFoundError: No module named flaskx",
                "stderr": "Traceback...\nModuleNotFoundError: No module named flaskx",
            }
        ],
        counters={"iterations": 0, "fix_attempts": 2, "command_failures": 3, "reverts": 0},
    )
    handoff = _build_investigate_handoff(st)
    actions = handoff["recommended_next_actions"]
    assert actions[0] == "verify_dependencies_and_import_paths"


def test_investigate_handoff_timeout_recommendations() -> None:
    st = ProjectState(
        errors=[
            {
                "source": "executor",
                "message": "run_command failed",
                "stderr": "process exceeded time budget [timeout]",
            }
        ],
        counters={"iterations": 0, "fix_attempts": 2, "command_failures": 3, "reverts": 0},
    )
    handoff = _build_investigate_handoff(st)
    actions = handoff["recommended_next_actions"]
    assert actions[0] == "reduce_command_scope_for_repro"
