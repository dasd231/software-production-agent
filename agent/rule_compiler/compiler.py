from __future__ import annotations

import hashlib
import re
from typing import Any

from agent.rule_compiler.schema import (
    APIContract,
    BusinessRuleCompilation,
    CompilationFinding,
    EntityField,
    EntitySchema,
    PermissionRule,
    StateTransition,
)


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(token in low or token in text for token in tokens)


def _clean_summary(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())[:600]


def _domain(text: str) -> str:
    if _has_any(text, ("退货", "退款", "售后", "return", "refund", "rma")):
        return "return_refund"
    if _has_any(text, ("审批", "请假", "报销", "approval", "expense")):
        return "approval_workflow"
    if _has_any(text, ("支付", "订单", "checkout", "payment", "order")):
        return "order_payment"
    if _has_any(text, ("权限", "角色", "rbac", "login", "登录")):
        return "access_control"
    return "generic_business_process"


def _base_fields() -> list[EntityField]:
    return [
        EntityField("id", "uuid", True, "primary key", indexed=True, unique=True),
        EntityField("tenant_id", "uuid", True, "tenant boundary", indexed=True),
        EntityField("created_at", "datetime", True, "creation time"),
        EntityField("updated_at", "datetime", True, "last update time"),
        EntityField("version", "int", True, "optimistic lock version"),
    ]


def _return_entities(text: str) -> list[EntitySchema]:
    fields = _base_fields() + [
        EntityField("order_id", "uuid", True, "original order id", indexed=True),
        EntityField("customer_id", "uuid", True, "request owner", indexed=True),
        EntityField("status", "enum", True, "return workflow state", indexed=True),
        EntityField("reason", "text", True, "customer supplied reason"),
        EntityField("evidence_urls", "json", False, "uploaded photos/videos"),
        EntityField("requested_amount_cents", "int", False, "expected refund amount"),
        EntityField("approved_amount_cents", "int", False, "approved refund amount"),
        EntityField("logistics_tracking_no", "string", False, "reverse logistics tracking number", indexed=True),
        EntityField("idempotency_key", "string", True, "dedupe key for create/transition APIs", indexed=True),
    ]
    constraints = [
        "unique(tenant_id, idempotency_key)",
        "status must be changed only by declared state transitions",
        "approved_amount_cents <= original paid amount",
    ]
    entities = [
        EntitySchema(
            "ReturnRequest",
            "return_requests",
            fields,
            indexes=[["tenant_id", "status"], ["tenant_id", "order_id"], ["tenant_id", "customer_id"]],
            constraints=constraints,
        ),
        EntitySchema(
            "ReturnAuditEvent",
            "return_audit_events",
            _base_fields()
            + [
                EntityField("return_request_id", "uuid", True, "return request id", indexed=True),
                EntityField("actor_id", "uuid", True, "operator/user id", indexed=True),
                EntityField("actor_role", "string", True, "role at decision time"),
                EntityField("event_type", "string", True, "transition or comment", indexed=True),
                EntityField("payload", "json", False, "decision evidence"),
            ],
            indexes=[["tenant_id", "return_request_id"], ["tenant_id", "event_type"]],
            constraints=["audit rows are append-only"],
        ),
    ]
    if _has_any(text, ("库存", "warehouse", "入库", "质检", "inspection")):
        entities.append(
            EntitySchema(
                "ReturnInspection",
                "return_inspections",
                _base_fields()
                + [
                    EntityField("return_request_id", "uuid", True, "return request id", indexed=True, unique=True),
                    EntityField("inspector_id", "uuid", True, "warehouse or QA operator"),
                    EntityField("result", "enum", True, "passed/failed/partial"),
                    EntityField("notes", "text", False, "inspection notes"),
                ],
                indexes=[["tenant_id", "result"]],
                constraints=["one inspection per return request"],
            )
        )
    return entities


def _generic_entities(domain: str) -> list[EntitySchema]:
    name = "BusinessRequest"
    table = "business_requests"
    return [
        EntitySchema(
            name,
            table,
            _base_fields()
            + [
                EntityField("requester_id", "uuid", True, "owner", indexed=True),
                EntityField("status", "enum", True, "workflow status", indexed=True),
                EntityField("title", "string", True, "business title"),
                EntityField("description", "text", False, "business detail"),
                EntityField("idempotency_key", "string", True, "dedupe key", indexed=True),
            ],
            indexes=[["tenant_id", "status"], ["tenant_id", "requester_id"]],
            constraints=[f"domain={domain}", "unique(tenant_id, idempotency_key)"],
        )
    ]


def _states(domain: str, text: str) -> list[str]:
    if domain == "return_refund":
        states = ["submitted", "under_review", "approved", "goods_returning"]
        if _has_any(text, ("质检", "验货", "inspection", "warehouse", "入库")):
            states.append("inspecting")
        states.extend(["refund_pending", "refunded", "rejected", "closed"])
        return states
    if domain == "approval_workflow":
        return ["draft", "submitted", "under_review", "approved", "rejected", "closed"]
    if domain == "order_payment":
        return ["created", "payment_pending", "paid", "fulfillment_pending", "fulfilled", "cancelled", "refunded"]
    return ["draft", "submitted", "processing", "approved", "rejected", "closed"]


def _return_transitions(states: list[str]) -> list[StateTransition]:
    transitions = [
        StateTransition("submit_return", "submitted", "under_review", ["customer"], "order is paid and return window is open"),
        StateTransition("approve_return", "under_review", "approved", ["support_agent", "admin"], "evidence passes policy checks"),
        StateTransition("reject_return", "under_review", "rejected", ["support_agent", "admin"], "policy violation or expired window"),
        StateTransition("ship_back_goods", "approved", "goods_returning", ["customer"], "reverse logistics label created"),
    ]
    if "inspecting" in states:
        transitions.append(
            StateTransition("receive_for_inspection", "goods_returning", "inspecting", ["warehouse_operator"], "goods arrived")
        )
        transitions.append(
            StateTransition(
                "inspection_passed",
                "inspecting",
                "refund_pending",
                ["warehouse_operator"],
                "inspection result is passed or partial",
            )
        )
    else:
        transitions.append(
            StateTransition("confirm_goods_received", "goods_returning", "refund_pending", ["warehouse_operator"], "goods arrived")
        )
    transitions.extend(
        [
            StateTransition(
                "issue_refund",
                "refund_pending",
                "refunded",
                ["finance", "system"],
                "provider refund succeeds",
                ["emit refund outbox message", "append audit event"],
                idempotency_key="tenant_id + return_request_id + transition",
            ),
            StateTransition("close_return", "refunded", "closed", ["system", "admin"], "post-refund settlement complete"),
        ]
    )
    return transitions


def _generic_transitions(states: list[str]) -> list[StateTransition]:
    return [
        StateTransition("submit", states[0], states[1], ["requester"]),
        StateTransition("approve", states[2] if len(states) > 2 else states[1], "approved", ["approver", "admin"]),
        StateTransition("reject", states[2] if len(states) > 2 else states[1], "rejected", ["approver", "admin"]),
        StateTransition("close", "approved", "closed", ["system", "admin"]),
    ]


def _permissions(domain: str) -> list[PermissionRule]:
    resource = "return_request" if domain == "return_refund" else "business_request"
    permissions = [
        PermissionRule("customer" if domain == "return_refund" else "requester", resource, ["create", "read", "cancel"], "own"),
        PermissionRule("support_agent" if domain == "return_refund" else "approver", resource, ["read", "review", "approve", "reject"], "tenant"),
        PermissionRule("admin", resource, ["read", "review", "approve", "reject", "override", "export"], "tenant"),
    ]
    if domain == "return_refund":
        permissions.extend(
            [
                PermissionRule("warehouse_operator", resource, ["read", "inspect", "receive_goods"], "tenant"),
                PermissionRule("finance", resource, ["read", "refund"], "tenant", "only refund_pending requests"),
            ]
        )
    return permissions


def _api_contracts(domain: str, transitions: list[StateTransition]) -> list[APIContract]:
    base = "/api/returns" if domain == "return_refund" else "/api/business-requests"
    resource_name = "ReturnRequest" if domain == "return_refund" else "BusinessRequest"
    contracts = [
        APIContract(
            "POST",
            base,
            f"create_{resource_name}",
            "authenticated",
            {"idempotency_key": "string", "payload": resource_name},
            {"id": "uuid", "status": "string"},
            idempotent=True,
            state_transition=transitions[0].name if transitions else "",
        ),
        APIContract("GET", base + "/{id}", f"get_{resource_name}", "authenticated + resource scope", {}, {"data": resource_name}),
        APIContract("GET", base, f"list_{resource_name}", "authenticated + tenant scope", {"status": "optional string"}, {"items": "array"}),
    ]
    for transition in transitions[1:]:
        contracts.append(
            APIContract(
                "POST",
                base + "/{id}/transitions/" + transition.name.replace("_", "-"),
                transition.name,
                "authenticated + role policy",
                {"idempotency_key": "string", "comment": "optional string"},
                {"id": "uuid", "from": transition.from_state, "to": transition.to_state},
                idempotent=bool(transition.idempotency_key or transition.to_state in {"refunded", "closed"}),
                state_transition=transition.name,
            )
        )
    return contracts


def _runtime_plan(domain: str) -> dict[str, Any]:
    return {
        "schema": "business_runtime_plan.v1",
        "runtime_hiding_layer": [
            "DB migration generated from entity schemas",
            "state transitions enforced by service layer, not frontend flags",
            "outbox/inbox used for payment/refund/logistics side effects",
            "deployment, rollback and migration are platform-owned operations",
        ],
        "recommended_components": [
            "FastAPI/Spring controller generated from API contracts",
            "service-level state machine guard",
            "RBAC policy middleware",
            "audit event writer",
            "idempotency-key store",
        ],
        "side_effect_boundaries": [
            "refund/payment provider",
            "logistics provider",
            "notification service",
        ]
        if domain == "return_refund"
        else ["notification service", "audit log"],
        "rollback_policy": "business rollback is compensating transition, never raw DB rewind after external side effect",
    }


def _progressive_enhancement(domain: str) -> list[dict[str, Any]]:
    items = [
        {
            "stage": "MVP",
            "capability": "manual workflow + RBAC + audit",
            "rule": "operators can process requests safely without hidden state mutation",
        },
        {
            "stage": "Automation",
            "capability": "rule engine suggestions",
            "rule": "system recommends approve/reject but human can override with audit reason",
        },
        {
            "stage": "Integration",
            "capability": "external provider connectors",
            "rule": "provider calls are idempotent and reconciled through outbox/inbox",
        },
    ]
    if domain == "return_refund":
        items.append(
            {
                "stage": "Model",
                "capability": "return fraud/risk small model",
                "rule": "model only changes review priority, not final refund authority without policy gate",
            }
        )
    return items


def _invariants(domain: str) -> list[str]:
    base = [
        "Every state change must append an audit event.",
        "Every mutating API must carry an idempotency key.",
        "State transitions must be monotonic through the declared state machine.",
        "Tenant boundary is part of every query predicate.",
        "External side effects are emitted through an outbox and reconciled.",
    ]
    if domain == "return_refund":
        base.extend(
            [
                "Refund amount cannot exceed captured payment amount.",
                "Refund execution requires refund_pending state.",
                "Customer can only read or operate their own return requests.",
            ]
        )
    return base


def _findings(
    *,
    text: str,
    domain: str,
    entities: list[EntitySchema],
    transitions: list[StateTransition],
    permissions: list[PermissionRule],
) -> list[CompilationFinding]:
    findings: list[CompilationFinding] = []
    if len(text.strip()) < 20:
        findings.append(
            CompilationFinding(
                "warning",
                "short_rule_source",
                "业务规则文本过短，当前编译结果主要来自默认模板。",
                "补充时间窗口、金额限制、角色、异常路径和外部系统。",
            )
        )
    if domain == "generic_business_process":
        findings.append(
            CompilationFinding(
                "warning",
                "generic_domain",
                "未识别出明确业务领域，已生成通用流程。",
                "使用更具体的业务词，例如退货、报销、审批、支付、库存。",
            )
        )
    if not entities:
        findings.append(CompilationFinding("error", "missing_entities", "未生成数据库实体。"))
    if not transitions:
        findings.append(CompilationFinding("error", "missing_state_transitions", "未生成状态机迁移。"))
    roles = {role for permission in permissions for role in [permission.role]}
    actor_roles = {role for transition in transitions for role in transition.actor_roles}
    missing_roles = sorted(actor_roles - roles - {"system"})
    if missing_roles:
        findings.append(
            CompilationFinding(
                "warning",
                "roles_without_permissions",
                f"状态机中存在未声明权限的角色: {', '.join(missing_roles)}",
                "补充权限矩阵或修正状态迁移角色。",
            )
        )
    if domain == "return_refund" and not _has_any(text, ("时间", "天", "window", "期限", "过期")):
        findings.append(
            CompilationFinding(
                "warning",
                "missing_return_window",
                "退货规则未明确退货期限。",
                "建议加入如签收后 7/15/30 天内可申请。",
            )
        )
    return findings


def compile_business_rules(rules: str, *, domain_hint: str = "") -> BusinessRuleCompilation:
    clean = str(rules or "").strip()
    domain = str(domain_hint or "").strip() or _domain(clean)
    if domain not in {"return_refund", "approval_workflow", "order_payment", "access_control", "generic_business_process"}:
        domain = _domain(clean)
    entities = _return_entities(clean) if domain == "return_refund" else _generic_entities(domain)
    states = _states(domain, clean)
    transitions = _return_transitions(states) if domain == "return_refund" else _generic_transitions(states)
    permissions = _permissions(domain)
    api_contracts = _api_contracts(domain, transitions)
    findings = _findings(text=clean, domain=domain, entities=entities, transitions=transitions, permissions=permissions)
    source_hash = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:12]
    return BusinessRuleCompilation(
        schema="business_rule_compilation.v1",
        domain=domain,
        source_summary=f"{_clean_summary(clean)} | source_hash={source_hash}",
        entities=entities,
        states=states,
        transitions=transitions,
        permissions=permissions,
        api_contracts=api_contracts,
        invariants=_invariants(domain),
        runtime_plan=_runtime_plan(domain),
        progressive_enhancement=_progressive_enhancement(domain),
        findings=findings,
    )

