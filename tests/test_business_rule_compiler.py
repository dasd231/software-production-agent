from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.rule_compiler import compile_business_rules


RETURN_RULES = """
用户签收后 7 天内可以申请退货退款。
客服审核通过后，用户寄回商品；仓库收到后需要质检。
质检通过进入退款，财务发起退款；退款成功后关闭售后单。
如果超过期限或者证据不足，客服可以拒绝。
"""


def test_compile_return_rules_to_schema_state_machine_permissions_and_api() -> None:
    compiled = compile_business_rules(RETURN_RULES)
    data = compiled.to_dict()

    assert compiled.ok is True
    assert data["domain"] == "return_refund"
    assert any(entity["name"] == "ReturnRequest" for entity in data["entities"])
    assert "inspecting" in data["state_machine"]["states"]
    transition_names = {item["name"] for item in data["state_machine"]["transitions"]}
    assert {"approve_return", "inspection_passed", "issue_refund"} <= transition_names
    assert any(permission["role"] == "finance" and "refund" in permission["actions"] for permission in data["permissions"])
    assert any(contract["path"].endswith("/transitions/issue-refund") for contract in data["api_contracts"])
    assert "Refund amount cannot exceed captured payment amount." in data["invariants"]


def test_compile_generic_short_rules_warns_but_still_outputs_contract() -> None:
    compiled = compile_business_rules("审批一下")
    data = compiled.to_dict()

    assert compiled.ok is True
    assert data["entities"]
    assert data["api_contracts"]
    codes = {finding["code"] for finding in data["findings"]}
    assert "short_rule_source" in codes


def test_business_rule_compile_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"business_rule_compile","args":'
        '{"rules":"用户签收后7天内退货，客服审核，仓库质检，财务退款",'
        '"output_path":"plans/rules.json"}}'
    )
    result = run_action(tmp_path, action)
    assert result["ok"] is True
    assert result["summary"]["domain"] == "return_refund"
    assert (tmp_path / "plans" / "rules.json").exists()

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
        limits=ExecutionLimits(granted_permissions=frozenset({"business:compile", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"

