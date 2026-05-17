from agent.skills.router import suggest_skills


def test_skill_router_api_goal() -> None:
    plan = {"stage": "coding", "tasks": ["build flask api"], "meta": {}}
    out = suggest_skills("write flask api", plan, {"progress": ""}, limit=4)
    names = [x["name"] for x in out]
    assert "python_flask_api" in names

