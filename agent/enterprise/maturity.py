"""Industrial-grade AI CTO maturity assessment and roadmap."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.enterprise.stack import build_enterprise_stack_plan
from agent.resources.registry import discover_resources


MATURITY_LEVELS = {
    0: "prototype",
    1: "repeatable",
    2: "controlled",
    3: "auditable",
    4: "resilient",
    5: "mission-grade",
}


def _counts(resources: dict[str, Any]) -> dict[str, int]:
    summary = resources.get("summary") if isinstance(resources.get("summary"), dict) else {}
    by_type = summary.get("by_type") if isinstance(summary.get("by_type"), dict) else {}
    return {str(k): int(v) for k, v in by_type.items()}


def _bool_score(value: bool, score: float) -> float:
    return score if value else 0.0


def _dimension(
    name: str,
    score: float,
    target_level: int,
    current_evidence: list[str],
    gaps: list[str],
    next_controls: list[str],
) -> dict[str, Any]:
    level = max(0, min(5, int(score // 20)))
    return {
        "name": name,
        "score": round(max(0.0, min(score, 100.0)), 1),
        "current_level": level,
        "current_label": MATURITY_LEVELS[level],
        "target_level": target_level,
        "target_label": MATURITY_LEVELS[target_level],
        "current_evidence": current_evidence,
        "gaps": gaps,
        "next_controls": next_controls,
    }


def _dimensions(counts: dict[str, int], stack_plan: dict[str, Any]) -> list[dict[str, Any]]:
    has_solution = counts.get("solution", 0) > 0
    has_dataset = counts.get("training_dataset", 0) > 0
    has_manifest = counts.get("run_manifest", 0) > 0
    has_ledger = counts.get("evidence_ledger", 0) > 0
    has_runtime = counts.get("model_runtime", 0) > 0
    chains = counts.get("chain", 0)
    stack_layers = {row.get("layer") for row in stack_plan.get("technology_choices", []) if isinstance(row, dict)}
    scenario_count = len(stack_plan.get("scenario_solutions", []))
    return [
        _dimension(
            "mission_and_scope_control",
            35 + _bool_score(chains >= 6, 20) + _bool_score("progressive_delivery" in stack_layers, 15),
            5,
            ["chain registry exists", "enterprise_stack_plan exists"],
            ["缺少 mission profile、禁用场景、SLO 和责任边界的正式文档"],
            ["建立 mission profile 模板", "每条 workflow 绑定 owner、SLO、禁用用途和验收门禁"],
        ),
        _dimension(
            "model_plane_governance",
            25 + _bool_score(has_runtime, 25) + _bool_score("model_runtime" in stack_layers, 20),
            5,
            ["model_runtime_status exposes OpenAI-compatible endpoint status"] if has_runtime else [],
            ["缺少 model registry、模型灰度路由、adapter 版本和离线评测基线"],
            ["建设 model registry", "上线 model gateway 灰度路由", "记录 model/workflow/rag index version"],
        ),
        _dimension(
            "rag_and_data_lineage",
            20 + _bool_score(has_solution, 20) + _bool_score(has_dataset, 15) + _bool_score(has_ledger, 25),
            5,
            ["solution library", "training dataset", "evidence ledger"] if has_ledger else ["solution/RAG/training assets partially present"],
            ["RAG index active/candidate 双版本、数据分级、脱敏和污染检测还不完整"],
            ["evidence ledger 作为训练筛选入口", "RAG index versioning", "PII/secret/license gate"],
        ),
        _dimension(
            "multi_agent_execution_control",
            30 + _bool_score(chains >= 8, 20) + _bool_score(has_manifest, 15),
            5,
            ["typed action protocol", "executor gateway", "workflow validation"],
            ["缺少 workflow executor、resource lease、公平队列和任务抢占策略"],
            ["实现 workflow executor", "引入 resource lease", "按 tenant/project/run_id 做公平队列"],
        ),
        _dimension(
            "release_and_hot_iteration",
            20 + _bool_score("progressive_delivery" in stack_layers, 25) + _bool_score(scenario_count >= 3, 15),
            5,
            ["enterprise stack includes canary/blue-green strategy"],
            ["缺少真实 CI/CD、Argo Rollouts、feature flags、自动回滚和数据库 expand-contract 流程"],
            ["容器化", "CI 安全门禁", "canary/blue-green", "feature flag kill switch"],
        ),
        _dimension(
            "security_supply_chain_and_compliance",
            20 + _bool_score("security_supply_chain" in stack_layers, 25) + _bool_score(has_ledger, 20),
            5,
            ["security supply chain choices documented", "manifest/evidence assets"] if has_ledger else ["security supply chain choices documented"],
            ["缺少 SBOM、SLSA provenance、SAST/DAST、依赖和镜像扫描的强制阻断"],
            ["生成 SBOM", "secret/license/CVE gate", "签名产物", "发布证据归档"],
        ),
        _dimension(
            "observability_and_incident_response",
            20 + _bool_score("observability" in stack_layers, 25) + _bool_score(has_manifest, 15),
            5,
            ["OpenTelemetry stack selected", "run manifests/events exist"],
            ["缺少统一 trace id、SLO dashboard、告警责任人、演练和事故回放模板"],
            ["OpenTelemetry trace propagation", "SLO/error-budget dashboard", "incident runbook and drills"],
        ),
        _dimension(
            "verification_and_evaluation",
            30 + _bool_score(has_manifest, 20) + _bool_score(has_dataset, 15) + _bool_score(has_ledger, 15),
            5,
            ["MetricReport layer", "run manifests", "training evaluation"] if has_manifest else ["MetricReport layer"],
            ["缺少任务级红队集、模型回归集、RAG 忠实度基线和发布阻断阈值"],
            ["建立 eval suite", "action JSON validity gate", "RAG faithfulness gate", "latency/cost/security gate"],
        ),
    ]


def _overall(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    score = sum(float(row["score"]) for row in dimensions) / max(len(dimensions), 1)
    level = max(0, min(5, int(score // 20)))
    blockers = [row["name"] for row in dimensions if int(row["current_level"]) < 3]
    return {
        "score": round(score, 1),
        "level": level,
        "label": MATURITY_LEVELS[level],
        "target_level": 5,
        "target_label": MATURITY_LEVELS[5],
        "primary_blockers": blockers[:6],
    }


def _cto_interrogation_pack() -> list[dict[str, Any]]:
    return [
        {
            "area": "model_governance",
            "questions": [
                "线上每个回答能否回放到 model_version、workflow_version、rag_index_version？",
                "新模型上线前 action JSON 合法率、RAG 忠实度、延迟和安全评测阈值是多少？",
                "模型拥塞或幻觉异常时如何一键回滚？",
            ],
            "required_evidence": ["model registry", "eval report", "gateway routing log", "rollback drill record"],
        },
        {
            "area": "multi_agent_control",
            "questions": [
                "多个 Agent 同时写 workspace 时如何防止互相覆盖？",
                "GPU、爬虫、训练和外部 API 是如何做资源租约和公平队列的？",
                "外部 API 不可用时哪些任务降级，哪些任务阻断？",
            ],
            "required_evidence": ["workflow manifest", "resource lease table", "tool gateway policy", "event trace"],
        },
        {
            "area": "data_and_rag",
            "questions": [
                "RAG 证据是否有来源、版本、权限和脱敏记录？",
                "训练样本如何证明不是从低质量聊天或受限代码里污染出来的？",
                "active/candidate RAG index 如何灰度和回滚？",
            ],
            "required_evidence": ["evidence ledger", "data classification", "training governance report", "index diff report"],
        },
        {
            "area": "release_and_incident",
            "questions": [
                "一次 workflow 或模型更新从提交到上线经过哪些强制门禁？",
                "是否支持 canary、blue-green、feature flag 和 kill switch？",
                "事故发生后 30 分钟内能否定位到租户、模型、工具调用和证据来源？",
            ],
            "required_evidence": ["CI pipeline", "Argo rollout history", "SLO dashboard", "incident runbook"],
        },
    ]


def _roadmap() -> list[dict[str, Any]]:
    return [
        {
            "horizon": "0-30 days",
            "goal": "从强原型到可控工程",
            "deliverables": [
                "定义 mission profile 和禁用场景",
                "实现 workflow executor MVP",
                "把 model_runtime_status 接入资源中心和告警",
                "CI 中加入 protocol/eval/security smoke gate",
            ],
        },
        {
            "horizon": "30-90 days",
            "goal": "从可控工程到可审计平台",
            "deliverables": [
                "model registry + model gateway 路由",
                "evidence ledger 作为训练样本入口",
                "RAG active/candidate index",
                "OpenTelemetry trace id 贯穿 Agent/Tool/Model/RAG",
            ],
        },
        {
            "horizon": "90-180 days",
            "goal": "从可审计平台到弹性生产",
            "deliverables": [
                "Kubernetes + Argo Rollouts canary/blue-green",
                "resource lease + fair queue",
                "SBOM/SLSA provenance/signing",
                "red-team eval suite and rollback drills",
            ],
        },
        {
            "horizon": "180-365 days",
            "goal": "逼近军工/安全关键成熟度",
            "deliverables": [
                "多租户隔离和数据分级",
                "灾备演练和供应链审计",
                "模型/Workflow/RAG 联动灰度",
                "合规证据包自动导出",
            ],
        },
    ]


def build_industrial_maturity_plan(
    goal: str,
    workspace: Path,
    *,
    scale: str = "listed",
    regulated: bool = True,
    provider: str = "main_deepseek",
) -> dict[str, Any]:
    clean_goal = " ".join(str(goal or "").split())[:4000]
    resources = discover_resources(workspace)
    counts = _counts(resources)
    stack_plan = build_enterprise_stack_plan(clean_goal, workspace, scale=scale, regulated=regulated, provider=provider)
    dimensions = _dimensions(counts, stack_plan)
    return {
        "schema": "industrial_maturity_plan.v1",
        "goal": clean_goal,
        "posture": "safety-critical-industrial-ai",
        "alignment_references": [
            "NIST AI RMF: govern/map/measure/manage risk functions",
            "NIST SSDF SP 800-218: secure software development practices",
            "NIST SP 800-53: security and privacy controls catalog",
            "SLSA: supply-chain provenance and build integrity levels",
        ],
        "overall": _overall(dimensions),
        "dimensions": dimensions,
        "cto_interrogation_pack": _cto_interrogation_pack(),
        "roadmap": _roadmap(),
        "non_negotiable_gates": [
            "no direct tool execution outside protocol.py/executor.py",
            "no model/workflow/rag release without eval and rollback plan",
            "no training sample without evidence lineage and governance report",
            "no external API dependency without timeout, fallback and audit",
            "no enterprise release without SBOM, secret scan, license/CVE gate and signed artifact",
        ],
        "resource_summary": resources.get("summary", {}),
    }
