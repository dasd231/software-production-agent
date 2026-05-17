"""Generate a product innovation radar from local platform resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.resources.registry import discover_resources
from agent.workflows.spec import validate_workflow_spec


@dataclass(frozen=True)
class InnovationCard:
    id: str
    title: str
    thesis: str
    why_now: str
    evidence: tuple[str, ...]
    next_steps: tuple[str, ...]
    impact: int
    confidence: int
    horizon: str = "near"

    @property
    def score(self) -> float:
        return round((max(0, min(self.impact, 10)) * 0.6) + (max(0, min(self.confidence, 10)) * 0.4), 2)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["evidence"] = list(self.evidence)
        out["next_steps"] = list(self.next_steps)
        out["score"] = self.score
        return out


def _counts(resources: dict[str, Any]) -> dict[str, int]:
    summary = resources.get("summary") if isinstance(resources.get("summary"), dict) else {}
    by_type = summary.get("by_type") if isinstance(summary.get("by_type"), dict) else {}
    return {str(k): int(v) for k, v in by_type.items()}


def _has_type(counts: dict[str, int], name: str) -> bool:
    return int(counts.get(name, 0)) > 0


def _platform_score(counts: dict[str, int]) -> float:
    signals = {
        "chain": 1.0,
        "model_provider": 1.0,
        "solution": 1.2,
        "knowledge_store": 1.2,
        "training_dataset": 1.3,
        "run_manifest": 1.1,
        "evidence_ledger": 1.2,
    }
    total_weight = sum(signals.values())
    earned = sum(weight for name, weight in signals.items() if _has_type(counts, name))
    return round(earned / total_weight * 100.0, 1)


def _foundation_cards(counts: dict[str, int]) -> list[InnovationCard]:
    cards: list[InnovationCard] = [
        InnovationCard(
            id="evidence_operating_system",
            title="证据操作系统",
            thesis="把方案库、RAG、Web、评价和训练样本都收敛到可追溯证据链，让 Agent 不只是会生成，而是会证明。",
            why_now="当前已经具备 solution、RAG、evaluation、manifest 的雏形，适合把证据链做成项目核心卖点。",
            evidence=(
                "research_synthesize 已包含证据仲裁能力",
                "crawler / RAG / research / training 共用统一评价结构",
                "run_manifest 已记录来源与风险",
            ),
            next_steps=(
                "把每次 answer 的 [S]/[R]/[W] 引用写入可搜索 evidence ledger",
                "在 UI 结果页展示证据覆盖率和冲突提示",
                "把 evidence ledger 接入训练样本筛选",
            ),
            impact=10,
            confidence=8,
        ),
        InnovationCard(
            id="software_factory_flywheel",
            title="软件工厂飞轮",
            thesis="每次生成的软件都沉淀为方案库，每次方案库都能进入 RAG 和训练，每次训练结果再反哺生成质量。",
            why_now="crawler、training_prepare、solution_manifest.v2 和 run_manifest 已经形成闭环的四个角。",
            evidence=(
                f"方案资产数量：{counts.get('solution', 0)}",
                f"训练数据集数量：{counts.get('training_dataset', 0)}",
                f"运行清单数量：{counts.get('run_manifest', 0)}",
                f"证据账本数量：{counts.get('evidence_ledger', 0)}",
            ),
            next_steps=(
                "把 solution_publish 接入结果页和工作流执行入口",
                "按 evaluation_score 自动筛选 training_eligible 样本",
                "做方案复用率和生成成功率趋势图",
            ),
            impact=10,
            confidence=7,
        ),
        InnovationCard(
            id="workflow_before_canvas",
            title="先有可验证工作流，再有画布",
            thesis="先用 workflow_validate 保证节点、权限、环路和执行顺序正确，再做可视化画布，避免 UI 先行导致系统不可控。",
            why_now="资源中心和分链注册已经存在，适合发展成低代码软件生产编排。",
            evidence=(
                f"已注册分链数量：{counts.get('chain', 0)}",
                "workflow_validate 已返回 DAG 顺序和权限信息",
                "chain_registry 已暴露成本等级与权限边界",
            ),
            next_steps=(
                "做 workflow template library",
                "在资源中心增加工作流模板预览",
                "把 workflow_dry_run report 接入意图编排页",
            ),
            impact=9,
            confidence=8,
        ),
        InnovationCard(
            id="governed_finetuning",
            title="可治理微调生产线",
            thesis="把微调从“攒数据”升级为“带引用、带治理、带风险报告、可回放”的数据生产线。",
            why_now="training_prepare 已有 quality、governance、evaluation_summary 和 run_manifest。",
            evidence=(
                "governance_report 已扫描疑似密钥内容",
                "quality_report 已保留引用率指标",
                "run_manifest 已追踪来源引用与风险",
            ),
            next_steps=(
                "加入许可证兼容性检查",
                "加入 train/eval contamination check",
                "输出 LLaMA-Factory/Axolotl config 草案",
            ),
            impact=9,
            confidence=7,
        ),
    ]
    if not _has_type(counts, "knowledge_store"):
        cards.append(
            InnovationCard(
                id="knowledge_bootstrap_gap",
                title="知识库冷启动缺口",
                thesis="系统想成为软件生产平台，必须让本地学习库成为默认资产，而不是可选附件。",
            why_now="资源中心暂未发现 knowledge_store，说明 RAG 飞轮还没完全转起来。",
            evidence=("知识库数量：0",),
                next_steps=(
                    "把成功 run 自动生成 knowledge_cards",
                    "给 /resources 增加知识库创建入口",
                    "把学习库健康度接入创新雷达评分",
                ),
                impact=8,
                confidence=9,
                horizon="immediate",
            )
        )
    return cards


def _workflow_templates() -> list[dict[str, Any]]:
    templates = [
        {
            "id": "research_to_training",
            "title": "方案研究到微调数据",
            "spec": {
                "schema": "workflow.v1",
                "version": "research-to-training.v1",
                "nodes": [{"id": "research", "chain": "research"}, {"id": "train", "chain": "training"}],
                "edges": [["research", "train"]],
            },
        },
        {
            "id": "crawl_to_solution_to_training",
            "title": "项目爬取到方案资产再到训练",
            "spec": {
                "schema": "workflow.v1",
                "version": "crawl-to-training.v1",
                "nodes": [
                    {"id": "crawl", "chain": "github_crawler"},
                    {"id": "publish", "chain": "solution_publish"},
                    {"id": "train", "chain": "training"},
                    {"id": "ledger", "chain": "evidence_ledger"},
                ],
                "edges": [["crawl", "publish"], ["publish", "train"], ["train", "ledger"]],
            },
        },
        {
            "id": "intent_to_asset",
            "title": "意图编译到证据资产",
            "spec": {
                "schema": "workflow.v1",
                "version": "intent-to-asset.v1",
                "nodes": [
                    {"id": "intent", "chain": "intent_compile"},
                    {"id": "dry_run", "chain": "workflow_dry_run"},
                    {"id": "research", "chain": "research"},
                    {"id": "publish", "chain": "solution_publish"},
                    {"id": "ledger", "chain": "evidence_ledger"},
                ],
                "edges": [["intent", "dry_run"], ["dry_run", "research"], ["research", "publish"], ["publish", "ledger"]],
            },
        },
        {
            "id": "context_research_loop",
            "title": "上下文增强到研究综合",
            "spec": {
                "schema": "workflow.v1",
                "version": "context-research.v1",
                "nodes": [{"id": "context", "chain": "context"}, {"id": "research", "chain": "research"}],
                "edges": [["context", "research"]],
            },
        },
    ]
    for template in templates:
        template["validation"] = validate_workflow_spec(template["spec"])
    return templates


def build_innovation_radar(workspace: Path, *, roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    resources = discover_resources(workspace, roots=roots)
    counts = _counts(resources)
    cards = sorted(_foundation_cards(counts), key=lambda card: (-card.score, card.id))
    platform_score = _platform_score(counts)
    return {
        "schema": "innovation_radar.v1",
        "north_star": "证据驱动的软件生产智能体平台",
        "positioning": "不是聊天机器人，而是能把需求、证据、方案、代码、评价、训练资产串成闭环的软件生产平台。",
        "platform_score": platform_score,
        "resource_summary": resources.get("summary", {}),
        "innovation_cards": [card.to_dict() for card in cards],
        "workflow_templates": _workflow_templates(),
        "signature_bets": [
            "证据账本：每次生成结果都尽量关联到本地或外部依据。",
            "软件工厂飞轮：运行结果可继续沉淀为方案、RAG 记忆和训练数据。",
            "工作流优先：先定义可验证契约，再进入可视化执行。",
        ],
        "recommended_next_build": cards[0].to_dict() if cards else {},
    }
