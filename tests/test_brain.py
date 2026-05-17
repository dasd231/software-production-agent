from agent.core.brain import _build_user_payload
from agent.memory.project_state import ProjectState


def test_build_user_payload_investigate_includes_priority_guidance() -> None:
    st = ProjectState()
    plan = {
        "stage": "investigate",
        "tasks": ["x"],
        "meta": {"recommended_next_actions": ["verify_dependencies_and_import_paths"]},
    }
    payload = _build_user_payload("goal", plan, st, {"ok": False}, "transcript")
    assert "priority_guidance" in payload
    pg = payload["priority_guidance"]
    assert pg["mode"] == "investigate"
    assert pg["must_consider_first"][0] == "verify_dependencies_and_import_paths"


def test_build_user_payload_non_investigate_has_no_priority_guidance() -> None:
    st = ProjectState()
    plan = {"stage": "coding", "tasks": ["x"], "meta": {}}
    payload = _build_user_payload("goal", plan, st, None, "")
    assert "priority_guidance" not in payload


def test_build_user_payload_contains_context_digest() -> None:
    st = ProjectState()
    st.structure = {
        "skill_hints": ["hint-a", "hint-b"],
        "rag_hints": ["rag-a", "rag-b"],
        "mcp_capabilities": [{"tool": "workspace.search"}],
    }
    payload = _build_user_payload("goal", {"stage": "coding", "tasks": [], "meta": {}}, st, None, "")
    digest = payload["context_digest"]
    assert digest["skill_hints"][0] == "hint-a"
    assert digest["rag_hints"][0] == "rag-a"
    assert digest["mcp_capabilities"][0]["tool"] == "workspace.search"
    assert digest["summary"]["rag_hints"]["total"] == 2


def test_build_user_payload_compacts_structured_rag_hints() -> None:
    st = ProjectState()
    st.structure = {
        "rag_hints": [
            {
                "path": "app.py",
                "line_start": 3,
                "line_end": 7,
                "score": 9,
                "overlap_tokens": ["flask", "hello", "route", "extra"],
                "line_overlap_tokens": ["hello", "route"],
                "size_bytes": 1234,
                "preview": "x" * 400,
                "truncated": True,
            }
        ],
    }
    payload = _build_user_payload("goal", {"stage": "coding", "tasks": [], "meta": {}}, st, None, "")
    hint = payload["context_digest"]["rag_hints"][0]
    assert hint["path"] == "app.py"
    assert hint["line_start"] == 3
    assert hint["line_end"] == 7
    assert hint["overlap_tokens"][:2] == ["flask", "hello"]
    assert hint["line_overlap_tokens"] == ["hello", "route"]
    assert hint["size_bytes"] == 1234
    assert len(hint["preview"]) == 260
    assert hint["truncated"] is True
