"""Registry for chain capabilities exposed to the main agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ChainDefinition:
    name: str
    action: str
    module: str
    description: str
    input_schema: str
    output_schema: str
    evaluation_stage: str
    permissions: tuple[str, ...] = ()
    writes_files: bool = False
    network_allowed: bool = False
    cost_level: str = "low"
    default_timeout_s: int = 120

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["permissions"] = list(self.permissions)
        return out


CHAIN_REGISTRY: dict[str, ChainDefinition] = {
    "context": ChainDefinition(
        name="context",
        action="internal_context",
        module="agent.chains.context",
        description="在每轮规划前注入技能提示、RAG 检索结果和 MCP 上下文。",
        input_schema="ContextChainInput",
        output_schema="ContextChainResult",
        evaluation_stage="rag.unified_retrieval",
        permissions=("workspace:read",),
    ),
    "intent_compile": ChainDefinition(
        name="intent_compile",
        action="intent_compile",
        module="agent.intent.compiler",
        description="把自然语言目标编译成可校验工作流，并生成预演结果和资源建议。",
        input_schema="IntentCompileInput",
        output_schema="IntentCompilation",
        evaluation_stage="workflow.intent_compile",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=60,
    ),
    "workflow_dry_run": ChainDefinition(
        name="workflow_dry_run",
        action="workflow_dry_run",
        module="agent.workflows.dry_run",
        description="在不真正执行节点的情况下，说明执行顺序、权限、预期输出和前置门禁。",
        input_schema="WorkflowSpec",
        output_schema="WorkflowDryRun",
        evaluation_stage="workflow.dry_run",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=60,
    ),
    "enterprise_stack": ChainDefinition(
        name="enterprise_stack",
        action="enterprise_stack_plan",
        module="agent.enterprise.stack",
        description="生成企业级技术选型、热迭代、模型平面和治理门禁方案。",
        input_schema="EnterpriseStackInput",
        output_schema="EnterpriseStackPlan",
        evaluation_stage="architecture.enterprise_stack",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=60,
    ),
    "industrial_maturity": ChainDefinition(
        name="industrial_maturity",
        action="industrial_maturity_plan",
        module="agent.enterprise.maturity",
        description="评估工业级 AI 成熟度，并输出 CTO 审查证据与路线图。",
        input_schema="IndustrialMaturityInput",
        output_schema="IndustrialMaturityPlan",
        evaluation_stage="architecture.industrial_maturity",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=60,
    ),
    "enterprise_readiness": ChainDefinition(
        name="enterprise_readiness",
        action="enterprise_readiness_check",
        module="agent.enterprise.readiness",
        description="针对平台、模型和部署基线执行企业上线静态门禁检查。",
        input_schema="EnterpriseReadinessInput",
        output_schema="EnterpriseReadinessReport",
        evaluation_stage="architecture.enterprise_readiness",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=60,
    ),
    "model_router": ChainDefinition(
        name="model_router",
        action="model_route_plan",
        module="agent.scheduler.routing",
        description="估算 token、识别负载类型，并把请求路由到短、长、Agent 或训练模型池。",
        input_schema="ModelRouteInput",
        output_schema="ModelRoutePlan",
        evaluation_stage="model.routing_admission",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=10,
    ),
    "model_admission": ChainDefinition(
        name="model_admission",
        action="model_admission_acquire",
        module="agent.scheduler.admission",
        description="获取模型池租约、限制各池并发，并在资源不足时返回回压决策。",
        input_schema="ModelAdmissionInput",
        output_schema="ModelAdmission",
        evaluation_stage="model.admission_control",
        permissions=("workspace:read",),
        cost_level="low",
        default_timeout_s=10,
    ),
    "integration_fabric": ChainDefinition(
        name="integration_fabric",
        action="integration_embed_plan",
        module="agent.integrations.embedding",
        description="规划第三方嵌入面板、资源选择器、动作桥接和事件回流。",
        input_schema="IntegrationEmbedRequest",
        output_schema="IntegrationEmbedPlan",
        evaluation_stage="integration.embed_admission",
        permissions=("workspace:read", "integration:read"),
        network_allowed=False,
        cost_level="low",
        default_timeout_s=10,
    ),
    "research": ChainDefinition(
        name="research",
        action="research_synthesize",
        module="agent.chains.research",
        description="综合本地方案库、RAG、可选 Web 与可选 LLM 证据。",
        input_schema="ResearchChainInput",
        output_schema="ResearchChainResult",
        evaluation_stage="research.synthesis",
        permissions=("workspace:read", "solution:read", "evidence:write"),
        writes_files=True,
        network_allowed=True,
        cost_level="medium",
        default_timeout_s=180,
    ),
    "training": ChainDefinition(
        name="training",
        action="training_prepare",
        module="agent.chains.training",
        description="从学习库和方案库中准备可审计的 SFT 数据集与训练计划。",
        input_schema="TrainingPrepareInput",
        output_schema="TrainingPrepareResult",
        evaluation_stage="training.dataset_prepare",
        permissions=("workspace:read", "dataset:write"),
        writes_files=True,
        cost_level="medium",
        default_timeout_s=240,
    ),
    "backup_model_training": ChainDefinition(
        name="backup_model_training",
        action="backup_model_train",
        module="agent.chains.model_training",
        description="基于高质量训练集生成备用本地模型训练任务、版本清单和环境门禁。",
        input_schema="BackupModelTrainInput",
        output_schema="BackupModelTrainResult",
        evaluation_stage="training.backup_model",
        permissions=("dataset:read", "model:write"),
        writes_files=True,
        cost_level="medium",
        default_timeout_s=120,
    ),
    "github_crawler": ChainDefinition(
        name="github_crawler",
        action="github_crawl_profile",
        module="agent.chains.github_crawler",
        description="分析 GitHub 或本地前后端仓库，并导出可复用方案。",
        input_schema="CrawlProfileInput",
        output_schema="CrawlProfileResult",
        evaluation_stage="crawler.run",
        permissions=("repo:read", "solution:write"),
        writes_files=True,
        network_allowed=True,
        cost_level="medium",
        default_timeout_s=300,
    ),
    "solution_publish": ChainDefinition(
        name="solution_publish",
        action="solution_publish",
        module="agent.solution_library.publish",
        description="把成功运行沉淀为可复用方案资产，并生成清单、备份文档和运行清单。",
        input_schema="SolutionPublishInput",
        output_schema="SolutionPublishResult",
        evaluation_stage="solution.publish",
        permissions=("workspace:read", "solution:write"),
        writes_files=True,
        cost_level="low",
        default_timeout_s=120,
    ),
    "evidence_ledger": ChainDefinition(
        name="evidence_ledger",
        action="evidence_ledger",
        module="agent.evidence.ledger",
        description="基于运行清单、方案清单、评价结果和事件日志生成本地证据账本。",
        input_schema="EvidenceLedgerInput",
        output_schema="EvidenceLedger",
        evaluation_stage="evidence.ledger",
        permissions=("workspace:read", "evidence:write"),
        writes_files=True,
        cost_level="low",
        default_timeout_s=90,
    ),
}


def list_chains() -> list[dict[str, Any]]:
    return [CHAIN_REGISTRY[name].to_dict() for name in sorted(CHAIN_REGISTRY)]


def get_chain(name_or_action: str) -> ChainDefinition | None:
    key = str(name_or_action or "").strip()
    if key in CHAIN_REGISTRY:
        return CHAIN_REGISTRY[key]
    for definition in CHAIN_REGISTRY.values():
        if definition.action == key:
            return definition
    return None
