from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.graph_runtime.property_graph import PropertyGraph


@dataclass(frozen=True, slots=True)
class CommandContract:
    name: str
    bounded_context: str
    intent: str
    action: str
    permissions: tuple[str, ...]
    input_schema: dict[str, str]
    output_schema: dict[str, str]
    side_effect: bool = False
    risk_level: str = "low"
    workflow_phase: str = "control"
    release_gates: tuple[str, ...] = ()
    observability: tuple[str, ...] = ("run_id", "trace_id", "command", "status", "latency_ms")
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["permissions"] = list(self.permissions)
        data["release_gates"] = list(self.release_gates)
        data["observability"] = list(self.observability)
        data["examples"] = list(self.examples)
        return data


COMMANDS: tuple[CommandContract, ...] = (
    CommandContract(
        name="CompileEnterpriseWorkflow",
        bounded_context="workflow_control_plane",
        intent="Turn Dify/YAML/business workflow into an enterprise LangGraph-like contract.",
        action="enterprise_workflow_compile",
        permissions=("workflow:compile", "workspace:write"),
        input_schema={"spec": "object optional", "goal": "string", "domain": "string"},
        output_schema={"contract": "enterprise_workflow_contract.v1", "cypher_seed": "string"},
        risk_level="medium",
        workflow_phase="compile",
        release_gates=("no blocker findings", "high risk nodes require human interrupt"),
        examples=("Dify workflow -> EnterpriseWorkflow contract",),
    ),
    CommandContract(
        name="QueryEnterpriseWorkflowGraph",
        bounded_context="workflow_graph_rag",
        intent="Ask governance questions over workflow contract graph.",
        action="enterprise_workflow_query",
        permissions=("workflow:read", "graph:read", "workspace:write"),
        input_schema={"query": "string", "spec": "object optional"},
        output_schema={"graph_rag": "graph_rag_result.v1", "insights": "array"},
        risk_level="medium",
        workflow_phase="governance_query",
        examples=("Which side-effect nodes need human review?",),
    ),
    CommandContract(
        name="PlanGraphRuntime",
        bounded_context="graph_memory",
        intent="Design LangGraph second-modification runtime and graph database memory plane.",
        action="graph_runtime_plan",
        permissions=("graph:plan", "workspace:write"),
        input_schema={"goal": "string", "include_cypher": "boolean"},
        output_schema={"plan": "graph_runtime_plan.v1"},
        risk_level="medium",
        workflow_phase="architecture",
    ),
    CommandContract(
        name="IngestAgentEventsGraph",
        bounded_context="graph_memory",
        intent="Convert .agent_events.jsonl into property graph assets.",
        action="graph_events_ingest",
        permissions=("graph:write", "workspace:read", "workspace:write"),
        input_schema={"events_path": "string", "query": "string optional"},
        output_schema={"graph": "property_graph.v1", "cypher": "string"},
        risk_level="medium",
        workflow_phase="observe",
        release_gates=("event schema valid", "secret redaction completed"),
    ),
    CommandContract(
        name="BuildOperationsReadiness",
        bounded_context="operations",
        intent="Produce health/logging/metrics/task-queue/multi-agent failover readiness plan.",
        action="operations_readiness_plan",
        permissions=("ops:plan", "workspace:write"),
        input_schema={"service_name": "string", "replicas": "int", "slo_target": "float"},
        output_schema={"plan": "operations_readiness_plan.v1"},
        risk_level="medium",
        workflow_phase="production_hardening",
        release_gates=("healthz ready", "DLQ runbook exists", "alerts configured"),
    ),
    CommandContract(
        name="PlanCloudNativeDeepDive",
        bounded_context="cloud_native_runtime",
        intent="Plan K8s scheduling/PV/CSI/CNI/etcd optimization for Agent workloads.",
        action="cloud_native_deep_dive_plan",
        permissions=("cloud:plan", "workspace:write"),
        input_schema={"focus": "string", "kubernetes_version": "string"},
        output_schema={"plan": "cloud_native_deep_dive_plan.v1"},
        risk_level="medium",
        workflow_phase="infrastructure_design",
    ),
    CommandContract(
        name="CompileBusinessRule",
        bounded_context="business_semantics",
        intent="Compile natural-language business/scientific rules into schema/state/API/permission contract.",
        action="business_rule_compile",
        permissions=("business:compile", "workspace:write"),
        input_schema={"rules": "string", "domain_hint": "string"},
        output_schema={"contract": "business_rule_compilation.v1"},
        risk_level="medium",
        workflow_phase="semantic_compile",
        release_gates=("state transition guards generated", "permission matrix reviewed"),
    ),
    CommandContract(
        name="PlanK8sSandbox",
        bounded_context="sandbox_runtime",
        intent="Render safe Kubernetes Job sandbox for risky command execution.",
        action="k8s_sandbox_plan",
        permissions=("sandbox:plan", "workspace:write"),
        input_schema={"command": "string", "image": "string", "namespace": "string"},
        output_schema={"manifest": "k8s_job_bundle.v1"},
        side_effect=True,
        risk_level="medium",
        workflow_phase="safe_execution",
        release_gates=("SecurityContext enforced", "NetworkPolicy reviewed", "resource limits set"),
    ),
    CommandContract(
        name="PlanContextPV",
        bounded_context="long_context_storage",
        intent="Plan semantic long-context slicing, placement, checksums and PV lifecycle.",
        action="context_pv_plan",
        permissions=("context:plan", "workspace:write"),
        input_schema={"text": "string", "query": "string optional"},
        output_schema={"manifest": "context_pv_manifest.v1"},
        risk_level="medium",
        workflow_phase="storage_compute_design",
    ),

    CommandContract(
        name="AcquireSkillBundle",
        bounded_context="skill_runtime",
        intent="Acquire task/format/reasoning skills before prompt assembly or action execution to prevent hallucinated scope, schema and reasoning.",
        action="skill_runtime_plan",
        permissions=("skill:read", "workspace:write"),
        input_schema={"goal": "string", "required_skill_ids": "string[] optional", "sample_output": "object|string optional"},
        output_schema={"plan": "skill_runtime_plan.v1", "bundle": "skill_bundle.v1", "validation": "contract_guard_report.v1 optional"},
        risk_level="low",
        workflow_phase="preflight",
        release_gates=("SkillBundle selected", "format contract valid", "hidden CoT not exposed"),
        examples=("Before code generation, acquire diff_intelligence + format/reasoning guards",),
    ),
    CommandContract(
        name="PlanAutomationScorecard",
        bounded_context="evaluation",
        intent="Build anti-cheat scorecard for automation effectiveness and evidence requirements.",
        action="automation_scorecard_plan",
        permissions=("evaluation:plan", "workspace:write"),
        input_schema={"demand_count": "int", "observation_days": "int"},
        output_schema={"scorecard": "automation_scorecard.v1"},
        risk_level="medium",
        workflow_phase="quality_gate",
    ),
)


def _bounded_contexts(commands: tuple[CommandContract, ...]) -> list[dict[str, Any]]:
    contexts: dict[str, list[CommandContract]] = {}
    for command in commands:
        contexts.setdefault(command.bounded_context, []).append(command)
    return [
        {
            "name": name,
            "command_count": len(items),
            "commands": [item.name for item in items],
            "risk_profile": sorted({item.risk_level for item in items}),
            "side_effect_commands": [item.name for item in items if item.side_effect],
        }
        for name, items in sorted(contexts.items())
    ]


def command_api_to_property_graph(commands: tuple[CommandContract, ...] = COMMANDS) -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("command_api", ("CommandAPI", "ArchitectureControlPlane"), purpose="large_project_cohesion")
    for command in commands:
        context_id = f"bounded_context:{command.bounded_context}"
        command_id = f"command:{command.name}"
        action_id = f"action:{command.action}"
        graph.add_node(context_id, ("BoundedContext",), name=command.bounded_context)
        graph.add_node(
            command_id,
            ("Command", "SideEffectCommand") if command.side_effect else ("Command",),
            name=command.name,
            intent=command.intent,
            risk_level=command.risk_level,
            workflow_phase=command.workflow_phase,
            permissions=list(command.permissions),
        )
        graph.add_node(action_id, ("ExecutorAction",), action=command.action)
        graph.add_edge("command_api", "HAS_CONTEXT", context_id)
        graph.add_edge(context_id, "OWNS_COMMAND", command_id)
        graph.add_edge(command_id, "BINDS_ACTION", action_id)
        for gate in command.release_gates:
            gate_id = f"gate:{command.name}:{abs(hash(gate))}"
            graph.add_node(gate_id, ("ReleaseGate",), description=gate)
            graph.add_edge(command_id, "REQUIRES_GATE", gate_id)
        for permission in command.permissions:
            perm_id = f"permission:{permission}"
            graph.add_node(perm_id, ("Permission",), name=permission)
            graph.add_edge(command_id, "REQUIRES_PERMISSION", perm_id)
    return graph


def _anti_looseness_rules() -> list[dict[str, str]]:
    return [
        {
            "problem": "Action 名称越来越多，模块边界变松散",
            "rule": "所有新 action 必须先注册 CommandContract，声明 bounded_context/permissions/risk/output_schema",
        },
        {
            "problem": "提示词分层越来越松散，任务/格式/思维链靠软约束",
            "rule": "执行前必须 AcquireSkillBundle，把任务契约、格式契约、可见推理摘要和所需 Skill 绑定成机器可校验对象",
        },
        {
            "problem": "副作用节点散落在工具调用里",
            "rule": "side_effect=True 的 command 必须有 idempotency/outbox/release gate/human review 策略",
        },
        {
            "problem": "workflow 快速搭起来但不可上线",
            "rule": "workflow 必须经过 enterprise_workflow_compile，生成 release_gates 后才能进入 pilot",
        },
        {
            "problem": "Graph-RAG 只查业务知识，不查系统经验",
            "rule": "Command、Workflow、ReleaseGate、Finding 都投影为 property graph，供治理查询使用",
        },
        {
            "problem": "大模型/小模型/工具职责混杂",
            "rule": "CommandAPI 只定义意图和契约，LangGraph/workflow 决定编排，小模型负责路由，大模型负责高价值推理",
        },
    ]


def build_command_api_plan(
    goal: str = "把软件生产 Agent 扩展成大项目级 AgentOS",
    *,
    focus: str = "large_project_cohesion",
    include_cypher: bool = True,
) -> dict[str, Any]:
    graph = command_api_to_property_graph(COMMANDS)
    commands = [command.to_dict() for command in COMMANDS]
    return {
        "schema": "command_api_plan.v1",
        "goal": goal,
        "focus": focus,
        "positioning": "CommandAPI defines stable capability boundaries; LangGraph-like workflow composes them dynamically.",
        "why_it_matters": [
            "Large Agent projects become loose when actions, prompts, tools and workflows grow without a command contract.",
            "CommandAPI makes each capability explicit: owner context, inputs, outputs, permissions, side effects, release gates and observability.",
            "LangGraph/Command handles dynamic routing; CommandAPI prevents dynamic routing from becoming ungoverned spaghetti.",
        ],
        "bounded_contexts": _bounded_contexts(COMMANDS),
        "commands": commands,
        "anti_looseness_rules": _anti_looseness_rules(),
        "architecture_layers": [
            {"layer": "CommandAPI", "responsibility": "stable capability contract and large-project boundary"},
            {"layer": "Enterprise Workflow Compiler", "responsibility": "turn Dify/YAML workflows into governed graph contracts"},
            {"layer": "LangGraph-like Runtime", "responsibility": "execute state graph with Command-style routing, checkpoint and interrupt"},
            {"layer": "Graph Memory", "responsibility": "persist command/workflow/risk/release-gate lineage"},
            {"layer": "Operations", "responsibility": "health, logs, metrics, queue lease, DLQ and SLO"},
        ],
        "graph_projection": graph.to_dict(),
        "cypher_seed": graph.to_cypher_seed() if include_cypher else "",
        "mermaid": graph.to_mermaid(),
        "interview_pitch": [
            "CommandAPI 解决大项目能力松散问题：每个能力先有契约，再被 workflow 编排。",
            "LangGraph 解决动态工作流问题：节点可以 Command goto，但 goto 的目标必须是受治理的 command/subgraph。",
            "二者结合后，项目既能快速搭 workflow，又不会变成一堆散乱工具调用。",
        ],
    }
