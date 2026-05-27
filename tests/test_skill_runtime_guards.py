from __future__ import annotations

import json

from agent.skill_runtime import ContractGuard, FormatContract, SkillRegistry, assemble_skill_bundle


def test_skill_bundle_selects_baseline_guards_and_relevant_skills() -> None:
    bundle = assemble_skill_bundle(
        "解决 RAG 相似性灾难，并输出结构化上下文包",
        task_id="skill_test",
        required_skill_ids=("skill.semantic_retrieval",),
    )
    skill_ids = {skill.skill_id for skill in bundle.selected_skills}
    assert {"skill.task_contract", "skill.format_contract", "skill.reasoning_brief", "skill.semantic_retrieval"} <= skill_ids
    assert bundle.task_contract.task_type in {"research", "planning"}
    assert bundle.format_contract.schema_name == "guarded_agent_response.v1"


def test_contract_guard_accepts_schema_valid_evidence_bound_output() -> None:
    bundle = assemble_skill_bundle(
        "解决任务幻化、格式幻化和思维链幻化，先获取 Skill 再执行",
        explicit_scope=("任务契约", "格式契约", "证据摘要", "SkillBundle"),
    )
    output = {
        "answer": "先获取 SkillBundle，再用任务契约、格式契约和证据摘要契约约束输出。",
        "evidence": [{"evidence_id": "doc:skill", "summary": "Skill 是执行前置能力包。"}],
        "risks": ["没有证据时必须标 unknown"],
        "next_actions": ["接入运行时前置校验"],
    }
    report = ContractGuard().validate(bundle, output, known_evidence_ids=("doc:skill",))
    assert report.ok is True
    assert report.normalized_output == output


def test_task_hallucination_guard_blocks_unrequested_deploy_train_and_delete() -> None:
    bundle = assemble_skill_bundle("只整理本地文档里的项目讲解方案", explicit_scope=("文档整理", "项目讲解", "本地"))
    output = {
        "answer": "我会直接部署到 production，删除旧数据，然后启动模型训练。",
        "evidence": [{"evidence_id": "doc:1"}],
        "risks": [],
        "next_actions": ["kubectl apply", "rm -rf old", "finetune model"],
    }
    report = ContractGuard().validate(bundle, output, known_evidence_ids=("doc:1",))
    codes = {v.code for v in report.violations}
    assert "UNAUTHORIZED_DEPLOY" in codes
    assert "UNAUTHORIZED_DELETE" in codes
    assert "UNAUTHORIZED_TRAIN" in codes
    assert report.ok is False


def test_format_hallucination_guard_blocks_extra_missing_and_wrong_type() -> None:
    bundle = assemble_skill_bundle(
        "输出严格 JSON",
        format_contract=FormatContract(
            schema_name="strict.v1",
            required_fields=("answer", "evidence"),
            optional_fields=("risks",),
            field_types={"answer": "str", "evidence": "list", "risks": "list"},
            allow_extra_fields=False,
        ),
    )
    bad = json.dumps({"answer": ["not string"], "extra": "漂移字段"}, ensure_ascii=False)
    report = ContractGuard().validate(bundle, bad)
    codes = {v.code for v in report.violations}
    assert {"MISSING_REQUIRED_FIELD", "EXTRA_FIELD", "FIELD_TYPE_MISMATCH"} <= codes
    assert report.ok is False


def test_reasoning_guard_blocks_hidden_cot_and_unknown_evidence() -> None:
    bundle = assemble_skill_bundle("给出证据绑定的短决策摘要")
    output = {
        "answer": "结论如下。",
        "reasoning": "这是我的 chain of thought：第一步我猜测，第二步我确认。",
        "evidence": [{"evidence_id": "invented:1", "summary": "不存在的证据"}],
        "risks": [],
        "next_actions": [],
    }
    report = ContractGuard().validate(bundle, output, known_evidence_ids=("real:1",))
    codes = {v.code for v in report.violations}
    assert "HIDDEN_COT_EXPOSED_OR_REQUESTED" in codes
    assert "FREEFORM_REASONING_FIELD" in codes
    assert "UNKNOWN_EVIDENCE_ID" in codes
    assert report.ok is False


def test_skill_registry_lists_machine_readable_skill_cards() -> None:
    skills = SkillRegistry().list_skills()
    assert skills
    assert all(skill.skill_id.startswith("skill.") for skill in skills)
    assert any("format_guard" in skill.capability_tags for skill in skills)

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded


def test_skill_runtime_plan_action_writes_bundle_and_respects_permissions(tmp_path) -> None:
    action = parse_action(
        '{"type":"action","action":"skill_runtime_plan","args":'
        '{"goal":"解决任务幻化、格式幻化、思维链幻化，先获取 Skill",'
        '"required_skill_ids":["skill.semantic_retrieval"],'
        '"explicit_scope":["任务契约","格式契约","SkillBundle"],'
        '"output_path":"plans/skill-runtime.json"}}'
    )
    denied = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    result = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"skill:read", "workspace:write"})),
    )
    assert result["ok"] is True
    assert result["summary"]["selected_skill_count"] >= 3
    assert (tmp_path / "plans" / "skill-runtime.json").exists()
    skill_ids = {item["skill_id"] for item in result["plan"]["bundle"]["selected_skills"]}
    assert "skill.semantic_retrieval" in skill_ids

from agent.graph_runtime import graph_rag_query, validate_property_graph_against_spec
from agent.skill_runtime import ContractGuard, assemble_skill_bundle, skill_runtime_graph_bundle, skill_runtime_to_property_graph


def test_skill_runtime_projects_bundle_and_guard_report_to_lpg() -> None:
    bundle = assemble_skill_bundle(
        "执行前获取 SkillBundle 并校验输出",
        required_skill_ids=("skill.reasoning_brief",),
        explicit_scope=("SkillBundle", "GuardReport"),
    )
    output = {
        "answer": "ok",
        "evidence": [{"evidence_id": "ev:skill"}],
        "risks": [],
        "next_actions": [],
    }
    report = ContractGuard().validate(bundle, output, known_evidence_ids=("ev:skill",))
    graph = skill_runtime_to_property_graph(
        run_id="skill-graph-run",
        node_name="guarded_node",
        skill_bundle=bundle.to_dict(),
        guard_report=report.to_dict(),
    )
    validation = validate_property_graph_against_spec(graph)
    assert validation["ok"] is True
    labels = {label for node in graph.nodes.values() for label in node.labels}
    assert {"SkillBundle", "SkillCard", "GuardReport", "TaskContract", "FormatContract", "ReasoningContract"} <= labels
    edge_types = {edge.type for edge in graph.edges}
    assert {"USED_SKILL", "GUARDED_BY", "VALIDATED_OUTPUT", "EVALUATED_BY"} <= edge_types
    query = graph_rag_query(graph, "SkillCard GuardReport", top_k=4)
    assert query["anchor_nodes"]
    bundle_payload = skill_runtime_graph_bundle(
        run_id="skill-graph-run",
        node_name="guarded_node",
        skill_bundle=bundle.to_dict(),
        guard_report=report.to_dict(),
    )
    assert "MERGE" in bundle_payload["cypher_seed"]
    assert "flowchart" in bundle_payload["mermaid"]
