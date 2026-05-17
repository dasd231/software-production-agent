import pytest

from agent.core.protocol import ActionDTO, ProtocolError, parse_and_validate_action_line


def test_write_file_roundtrip() -> None:
    line = '{"type":"action","action":"write_file","args":{"path":"a.txt","content":"hi"}}'
    d = parse_and_validate_action_line(line)
    assert d["action"] == "write_file"
    dto = ActionDTO.model_validate(d)
    assert dto.action == "write_file"


def test_reject_unknown_action() -> None:
    with pytest.raises(ProtocolError):
        parse_and_validate_action_line('{"type":"action","action":"rm_rf","args":{}}')


def test_fence_extraction() -> None:
    line = 'Here:\n```json\n{"type":"action","action":"finish","args":{"reason":"x"}}\n```'
    d = parse_and_validate_action_line(line)
    assert d["action"] == "finish"


def test_noise_extraction_uses_first_balanced_object() -> None:
    line = (
        'prefix {"type":"action","action":"finish","args":{"reason":"first {ok}"}} '
        '{"type":"action","action":"finish","args":{"reason":"second"}}'
    )
    d = parse_and_validate_action_line(line)
    assert d["args"]["reason"] == "first {ok}"


def test_workspace_index_rejects_extra_args() -> None:
    with pytest.raises(ProtocolError):
        parse_and_validate_action_line('{"type":"action","action":"workspace_index","args":{"x":1}}')


def test_mcp_call_requires_tool() -> None:
    with pytest.raises(ProtocolError):
        parse_and_validate_action_line('{"type":"action","action":"mcp_call","args":{"args":{"query":"x"}}}')


def test_mcp_call_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"mcp_call","args":{"tool":"workspace.search","args":{"query":"flask"}}}'
    )
    assert d["action"] == "mcp_call"


def test_mcp_capabilities_rejects_extra_args() -> None:
    with pytest.raises(ProtocolError):
        parse_and_validate_action_line('{"type":"action","action":"mcp_capabilities","args":{"x":1}}')


def test_mcp_capabilities_valid() -> None:
    d = parse_and_validate_action_line('{"type":"action","action":"mcp_capabilities","args":{}}')
    assert d["action"] == "mcp_capabilities"


def test_production_check_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"production_check","args":{"include_pytest":true,"timeout":30}}'
    )
    assert d["action"] == "production_check"


def test_production_check_rejects_bad_timeout() -> None:
    with pytest.raises(ProtocolError):
        parse_and_validate_action_line('{"type":"action","action":"production_check","args":{"timeout":"slow"}}')


def test_run_command_rejects_non_positive_timeout() -> None:
    with pytest.raises(ProtocolError, match="timeout must be positive"):
        parse_and_validate_action_line('{"type":"action","action":"run_command","args":{"command":"python -V","timeout":0}}')


def test_run_command_rejects_non_finite_timeout() -> None:
    with pytest.raises(ProtocolError, match="timeout must be finite"):
        parse_and_validate_action_line(
            '{"type":"action","action":"run_command","args":{"command":"python -V","timeout":NaN}}'
        )


def test_production_check_rejects_non_positive_timeout() -> None:
    with pytest.raises(ProtocolError, match="production_check timeout must be positive"):
        parse_and_validate_action_line('{"type":"action","action":"production_check","args":{"timeout":-1}}')


def test_chain_registry_valid() -> None:
    d = parse_and_validate_action_line('{"type":"action","action":"chain_registry","args":{"name":"research"}}')
    assert d["action"] == "chain_registry"


def test_resource_registry_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"resource_registry","args":{"type":"solution","roots":["./product_runs"]}}'
    )
    assert d["action"] == "resource_registry"


def test_integration_actions_valid() -> None:
    samples = [
        '{"type":"action","action":"integration_catalog","args":{"category":"design"}}',
        '{"type":"action","action":"integration_embed_plan","args":{"integration_id":"figma","resource_url":"https://www.figma.com/file/abc/Product","mode":"embed_panel","requested_capabilities":["frame_selection"]}}',
    ]
    for line in samples:
        assert parse_and_validate_action_line(line)["type"] == "action"


def test_integration_embed_plan_rejects_bad_capabilities() -> None:
    with pytest.raises(ProtocolError, match="requested_capabilities"):
        parse_and_validate_action_line(
            '{"type":"action","action":"integration_embed_plan","args":{"integration_id":"figma","requested_capabilities":"frame_selection"}}'
        )


def test_model_runtime_status_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"model_runtime_status","args":{"provider":"main_deepseek","probe":false,"timeout":2}}'
    )
    assert d["action"] == "model_runtime_status"


def test_model_runtime_status_rejects_bad_probe() -> None:
    with pytest.raises(ProtocolError, match="probe must be boolean"):
        parse_and_validate_action_line(
            '{"type":"action","action":"model_runtime_status","args":{"provider":"main_deepseek","probe":"yes"}}'
        )


def test_model_route_plan_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"model_route_plan","args":{"goal":"长上下文RAG","prompt":"上下文","business_type":"long","require_json":false,"max_output_tokens":2048}}'
    )
    assert d["action"] == "model_route_plan"


def test_model_route_plan_rejects_bad_max_output() -> None:
    with pytest.raises(ProtocolError, match="max_output_tokens"):
        parse_and_validate_action_line(
            '{"type":"action","action":"model_route_plan","args":{"goal":"x","max_output_tokens":0}}'
        )


def test_model_admission_actions_valid() -> None:
    samples = [
        '{"type":"action","action":"model_admission_status","args":{}}',
        '{"type":"action","action":"model_admission_acquire","args":{"goal":"短API","max_output_tokens":256,"idempotency_key":"req-1","lease_ttl_s":20}}',
        '{"type":"action","action":"model_admission_release","args":{"lease_id":"lease-1"}}',
        '{"type":"action","action":"model_admission_renew","args":{"lease_id":"lease-1","lease_ttl_s":20}}',
    ]
    for line in samples:
        assert parse_and_validate_action_line(line)["type"] == "action"


def test_model_admission_acquire_rejects_bad_ttl() -> None:
    with pytest.raises(ProtocolError, match="lease_ttl_s"):
        parse_and_validate_action_line(
            '{"type":"action","action":"model_admission_acquire","args":{"goal":"x","lease_ttl_s":0}}'
        )


def test_model_admission_release_requires_lease_id() -> None:
    with pytest.raises(ProtocolError, match="lease_id"):
        parse_and_validate_action_line('{"type":"action","action":"model_admission_release","args":{}}')


def test_enterprise_stack_plan_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"enterprise_stack_plan","args":{"goal":"上市企业私有化AI平台","scale":"listed","regulated":true,"provider":"main_deepseek"}}'
    )
    assert d["action"] == "enterprise_stack_plan"


def test_enterprise_stack_plan_requires_goal() -> None:
    with pytest.raises(ProtocolError, match="requires string goal"):
        parse_and_validate_action_line('{"type":"action","action":"enterprise_stack_plan","args":{"scale":"listed"}}')


def test_industrial_maturity_plan_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"industrial_maturity_plan","args":{"goal":"安全关键工业AI成熟度","scale":"listed","regulated":true,"provider":"main_deepseek"}}'
    )
    assert d["action"] == "industrial_maturity_plan"


def test_distillation_execution_actions_valid() -> None:
    samples = [
        '{"type":"action","action":"teacher_prompt_batch_build","args":{"distillation_plan":{},"source_examples":[],"max_prompts":0}}',
        '{"type":"action","action":"teacher_execution_plan_build","args":{"distillation_plan":{},"prompt_batch":{},"mode":"dry_run","allow_remote":false,"max_prompts":0,"max_output_tokens":1024,"temperature":0.0}}',
        '{"type":"action","action":"teacher_output_review_build","args":{"distillation_plan":{},"prompt_batch":{},"teacher_outputs":[]}}',
        '{"type":"action","action":"distillation_export_build","args":{"output_dir":"./distill","distillation_plan":{},"teacher_output_review":{}}}',
    ]
    for line in samples:
        assert parse_and_validate_action_line(line)["type"] == "action"


def test_industrial_maturity_plan_requires_goal() -> None:
    with pytest.raises(ProtocolError, match="requires string goal"):
        parse_and_validate_action_line('{"type":"action","action":"industrial_maturity_plan","args":{"scale":"listed"}}')


def test_enterprise_readiness_check_valid() -> None:
    d = parse_and_validate_action_line('{"type":"action","action":"enterprise_readiness_check","args":{}}')
    assert d["action"] == "enterprise_readiness_check"


def test_enterprise_readiness_check_rejects_args() -> None:
    with pytest.raises(ProtocolError, match="accepts no args"):
        parse_and_validate_action_line('{"type":"action","action":"enterprise_readiness_check","args":{"x":1}}')


def test_workflow_validate_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"workflow_validate","args":{"spec":{"nodes":["research"],"edges":[]}}}'
    )
    assert d["action"] == "workflow_validate"


def test_innovation_radar_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"innovation_radar","args":{"roots":["./product_runs"]}}'
    )
    assert d["action"] == "innovation_radar"


def test_intent_agentos_actions_valid() -> None:
    samples = [
        '{"type":"action","action":"intent_compile","args":{"goal":"爬取前后端并训练","roots":["./product_runs"]}}',
        '{"type":"action","action":"workflow_dry_run","args":{"spec":{"nodes":["research"],"edges":[]}}}',
        '{"type":"action","action":"evidence_ledger","args":{"roots":["./product_runs"],"output_path":"evidence_ledger.json"}}',
        '{"type":"action","action":"solution_publish","args":{"output_dir":"./solutions","title":"demo"}}',
    ]
    for line in samples:
        assert parse_and_validate_action_line(line)["type"] == "action"


def test_intent_compile_requires_goal() -> None:
    with pytest.raises(ProtocolError, match="intent_compile requires string goal"):
        parse_and_validate_action_line('{"type":"action","action":"intent_compile","args":{}}')


def test_research_synthesize_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"research_synthesize","args":{"query":"员工管理","top_k":2,"use_web":false,"use_llm":false,"solution_dirs":["./product_runs"],"learning_dirs":["./learning_runs/demo"]}}'
    )
    assert d["action"] == "research_synthesize"


def test_research_synthesize_rejects_bad_dirs() -> None:
    with pytest.raises(ProtocolError, match="solution_dirs must be string array"):
        parse_and_validate_action_line(
            '{"type":"action","action":"research_synthesize","args":{"query":"x","solution_dirs":"./product_runs"}}'
        )


def test_training_prepare_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"training_prepare","args":{"output_dir":"./training_runs/demo","learning_dirs":["./learning_runs/demo"],"solution_dirs":["./product_runs"],"dataset_format":"messages","eval_ratio":0.2,"min_chars":20,"max_examples":100,"include_protocol_examples":true,"protocol_example_limit":10}}'
    )
    assert d["action"] == "training_prepare"


def test_training_prepare_rejects_bad_eval_ratio() -> None:
    with pytest.raises(ProtocolError, match="eval_ratio"):
        parse_and_validate_action_line(
            '{"type":"action","action":"training_prepare","args":{"output_dir":"./out","eval_ratio":"many"}}'
        )


def test_training_prepare_rejects_bad_protocol_limit() -> None:
    with pytest.raises(ProtocolError, match="protocol_example_limit"):
        parse_and_validate_action_line(
            '{"type":"action","action":"training_prepare","args":{"output_dir":"./out","protocol_example_limit":-1}}'
        )


def test_backup_model_train_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"backup_model_train","args":{"training_dir":"./training","output_dir":"./backup","min_train_examples":10,"launch":false}}'
    )
    assert d["action"] == "backup_model_train"


def test_github_crawl_profile_valid() -> None:
    d = parse_and_validate_action_line(
        '{"type":"action","action":"github_crawl_profile","args":{"query":"spring vue","output_dir":"./crawl_runs/demo","github":false,"local_repos":["./repo"],"repo_limit":1,"min_stars":0,"quality_threshold":6.5}}'
    )
    assert d["action"] == "github_crawl_profile"


def test_github_crawl_profile_rejects_bad_local_repos() -> None:
    with pytest.raises(ProtocolError, match="local_repos"):
        parse_and_validate_action_line(
            '{"type":"action","action":"github_crawl_profile","args":{"output_dir":"./out","local_repos":"./repo"}}'
        )
