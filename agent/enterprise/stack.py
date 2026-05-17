"""Enterprise technology stack and rollout planning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.llm.runtime import model_runtime_status
from agent.resources.registry import discover_resources


def _tokens(text: str) -> set[str]:
    return {part.lower() for part in re.findall(r"[A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,}", text or "")}


def _has(goal: str, words: tuple[str, ...]) -> bool:
    text = goal.lower()
    return any(word.lower() in text or word in goal for word in words)


def _scale_tier(goal: str, requested: str) -> str:
    value = requested.strip().lower()
    if value in {"startup", "team", "department", "enterprise", "listed"}:
        return value
    if _has(goal, ("上市", "集团", "多租户", "高并发", "10万", "百万", "审计", "合规")):
        return "listed"
    if _has(goal, ("企业", "公司", "权限", "审批", "部门")):
        return "enterprise"
    return "department"


def _risk_profile(goal: str, regulated: bool) -> dict[str, Any]:
    tags: list[str] = []
    if regulated or _has(goal, ("金融", "医疗", "政企", "审计", "等保", "合规", "隐私")):
        tags.extend(["regulated", "audit-required", "data-protection"])
    if _has(goal, ("登录", "权限", "角色", "rbac", "sso")):
        tags.append("identity-sensitive")
    if _has(goal, ("训练", "微调", "模型", "大模型", "rag", "知识库")):
        tags.append("model-data-governance")
    if _has(goal, ("高并发", "实时", "消息", "队列")):
        tags.append("high-throughput")
    return {
        "risk_tags": list(dict.fromkeys(tags)),
        "default_posture": "change-control-first" if tags else "standard-enterprise",
        "human_approval_required": bool(tags),
    }


def _choice(layer: str, primary: str, alternatives: list[str], rationale: str, gates: list[str]) -> dict[str, Any]:
    return {
        "layer": layer,
        "primary": primary,
        "alternatives": alternatives,
        "rationale": rationale,
        "enterprise_gates": gates,
    }


def _technology_choices(goal: str, tier: str) -> list[dict[str, Any]]:
    listed = tier == "listed"
    choices = [
        _choice(
            "control_plane",
            "FastAPI ASGI platform gateway + typed action protocol",
            ["Spring Boot control service", "Go service"],
            "Expose enterprise-grade async APIs while keeping protocol.py/executor.py as the execution boundary; Flask remains local UI only.",
            ["OpenAPI contract", "request audit log", "idempotency keys"],
        ),
        _choice(
            "product_backend",
            "Spring Boot 3 + Java 21",
            ["FastAPI", ".NET 8"],
            "Conservative enterprise default for business systems, RBAC, audit and integration-heavy domains.",
            ["contract tests", "dependency scan", "API versioning"],
        ),
        _choice(
            "product_frontend",
            "Vue 3 + TypeScript + Vite",
            ["React + TypeScript", "Angular"],
            "Fits current generated artifacts and keeps admin/operational UI dense and maintainable.",
            ["component story coverage", "accessibility smoke tests", "frontend bundle budget"],
        ),
        _choice(
            "data_plane",
            "PostgreSQL + Flyway",
            ["MySQL", "PolarDB-compatible PostgreSQL"],
            "Strong relational default with migration discipline for product records and audit tables.",
            ["migration review", "backup restore drill", "slow query budget"],
        ),
        _choice(
            "cache",
            "Redis",
            ["KeyDB", "Dragonfly"],
            "Session, rate limit and hot lookup cache; keep it replaceable behind a small adapter.",
            ["ttl policy", "cache stampede guard", "fail-open/fail-closed decision"],
        ),
        _choice(
            "event_bus",
            "Kafka",
            ["Pulsar", "RabbitMQ"],
            "Decouple crawler, training, evaluation, publish and audit events as the platform scales.",
            ["schema registry", "dead-letter queue", "consumer lag alert"],
        ),
        _choice(
            "distributed_execution",
            "Ray",
            ["Celery for small queues", "Kubernetes Jobs for coarse batch"],
            "Use Ray as the first distributed execution substrate for Python-native agent, learning, evaluation and training-dispatch workloads while keeping control-plane manifests authoritative.",
            ["resource labels", "retry policy", "queue observability", "no direct business-rule ownership"],
        ),
        _choice(
            "batch_data_processing",
            "Spark + Parquet/object storage",
            ["DuckDB/Polars before scale", "Beam if runner portability later matters"],
            "Use Spark only when dataset construction outgrows local Python/JSONL preparation; keep it focused on large-scale data transforms rather than workflow semantics.",
            ["dataset versioning", "schema evolution", "partition strategy", "lineage export"],
        ),
        _choice(
            "stream_processing",
            "Flink when real-time stateful needs appear",
            ["Kafka Streams", "Spark Structured Streaming"],
            "Introduce Flink for genuinely stateful event-time processing such as audit streams, online monitoring and feature updates, not as premature architecture decoration.",
            ["event-time semantics", "checkpointing", "state recovery", "consumer lag SLO"],
        ),
        _choice(
            "identity",
            "OIDC/OAuth2 + SSO gateway",
            ["Keycloak", "Auth0/Entra ID integration"],
            "Enterprise users need SSO, role mapping and auditable session control.",
            ["RBAC matrix", "admin break-glass", "session revocation"],
        ),
        _choice(
            "model_runtime",
            "vLLM OpenAI-compatible service",
            ["SGLang OpenAI-compatible service", "Transformers FastAPI for dev fallback", "llama.cpp server for edge-only fallback"],
            "Use vLLM/SGLang for production throughput; avoid Ollama as a production serving plane and keep OpenAI-compatible boundary so runtimes can swap.",
            ["health probe", "model allowlist", "prompt/response audit sampling"],
        ),
        _choice(
            "orchestration",
            "Kubernetes",
            ["Docker Compose for dev", "Nomad"],
            "Standard enterprise deployment substrate for rolling updates, probes and resource isolation.",
            ["readiness probe", "resource quota", "pod disruption budget"],
        ),
        _choice(
            "progressive_delivery",
            "Argo Rollouts canary/blue-green",
            ["Kubernetes rolling update", "Flagger"],
            "Hot iteration should route small traffic first, observe metrics, then promote or rollback.",
            ["canary analysis", "automatic rollback", "manual approval gate" if listed else "release note"],
        ),
        _choice(
            "observability",
            "OpenTelemetry + Prometheus/Grafana + Loki",
            ["Datadog", "Elastic Observability"],
            "One trace/log/metric language across Agent loop, model gateway, workflow executor and product services.",
            ["trace id propagation", "SLO dashboard", "alert ownership"],
        ),
        _choice(
            "security_supply_chain",
            "SBOM + SAST + dependency/container scan",
            ["Snyk", "Trivy", "OWASP Dependency-Check"],
            "Generated code and crawled assets must be scanned before enterprise promotion.",
            ["license policy", "secret scan", "critical CVE block"],
        ),
    ]
    if _has(goal, ("搜索", "日志检索", "知识库", "全文")):
        choices.append(
            _choice(
                "search",
                "OpenSearch",
                ["Elasticsearch", "PostgreSQL full-text"],
                "Full-text retrieval for solution library, audit events and knowledge assets.",
                ["index lifecycle", "PII masking", "query latency SLO"],
            )
        )
    return choices


def _hot_iteration_strategy(tier: str) -> dict[str, Any]:
    listed = tier == "listed"
    return {
        "strategy": "canary_then_blue_green" if listed else "rolling_then_canary",
        "release_flow": [
            "merge request with architecture decision record",
            "CI: unit, contract, protocol, security and migration checks",
            "build immutable image and SBOM",
            "deploy canary with 1-5% traffic",
            "observe SLO, error budget, action JSON validity and model latency",
            "promote, rollback or hold for manual approval",
        ],
        "feature_control": {
            "flags": ["workflow_executor", "model_router", "training_pipeline", "web_search"],
            "kill_switch_required": True,
            "config_reload": "env/configmap reload first; process hot patch only for non-stateful routing rules",
        },
        "database_change_policy": [
            "expand-contract migrations",
            "backfill jobs are idempotent",
            "no destructive schema changes in the same release",
        ],
    }


def _model_plane(provider_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "runtime_boundary": "OpenAI-compatible /v1 API",
        "recommended_serving": "vLLM for production; Transformers server for Windows/dev fallback",
        "current_status": provider_status,
        "router_policy": [
            {"task": "coding/action-json", "preferred": "coder or high-instruction-following model"},
            {"task": "research synthesis", "preferred": "reasoner model with citation prompt"},
            {"task": "fast UI iteration", "preferred": "small fast model or local_production fallback"},
        ],
        "deployment_units": [
            "model-gateway: auth, rate limit, audit and request shaping",
            "model-runtime: vLLM/Transformers runtime",
            "model-registry: allowed models, adapters, eval score and rollout stage",
        ],
    }


def _scenario_solutions(goal: str, tier: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "llm_serving_selection",
            "question": "工业生产级私有化场景中，如何做 vLLM 与 SGLang 的技术选型？高并发接口请求和 32K+ 超长上下文分别做哪些核心配置优化？",
            "answer": "默认以 vLLM 作为企业生产通用推理底座，以 SGLang 作为结构化 Agent/工具调用和复杂前缀复用场景的专项底座；二者统一收敛到 OpenAI-compatible model gateway。",
            "selection_matrix": [
                {
                    "scenario": "高并发短/中上下文 API",
                    "preferred": "vLLM",
                    "why": "成熟的 OpenAI-compatible serving、PagedAttention、continuous batching、量化和多 GPU 并行更适合作为通用平台入口。",
                    "core_knobs": [
                        "--max-model-len 按业务上下文上限设置，避免无谓 KV cache 预留",
                        "--gpu-memory-utilization 0.80-0.92，给系统和峰值留余量",
                        "--tensor-parallel-size 按模型和 GPU 拆分",
                        "启用 prefix caching/automatic prefix caching 以复用系统提示词和企业知识前缀",
                        "按 p95 latency 与 GPU cache hit rate 调整 max-num-seqs / max-num-batched-tokens",
                    ],
                },
                {
                    "scenario": "32K+ 长上下文、长文档问答、RAG 大前缀复用",
                    "preferred": "vLLM 或 SGLang 双轨压测后定",
                    "why": "长上下文瓶颈主要在 prefill、KV cache 和排队；需要 chunked prefill、prefix/radix cache、上下文裁剪和分层 RAG 同时配合。",
                    "core_knobs": [
                        "把 RAG 做成 hierarchical retrieval，避免每次塞满 32K",
                        "开启 chunked prefill，避免长请求饿死短请求",
                        "长上下文请求单独队列和单独模型池，避免污染高并发短请求 SLA",
                        "对企业固定系统提示词/政策文本做 prefix cache 预热",
                        "按 max_total_tokens / KV cache 水位做 admission control",
                    ],
                },
                {
                    "scenario": "多 Agent 工具调用、结构化 JSON、复杂提示模板复用",
                    "preferred": "SGLang",
                    "why": "SGLang 的 RadixAttention、结构化输出和语言模型程序抽象更适合大量共享前缀、工具调用和受约束输出。",
                    "core_knobs": [
                        "max_running_requests 按 GPU 和 p95 latency 压测设定",
                        "max_total_tokens 作为硬限额，避免 Agent 长对话拖垮服务",
                        "chunked_prefill_size / max_prefill_tokens 分离调优",
                        "对 JSON/tool-call 启用 structured outputs 或 grammar 约束",
                        "打开 metrics 并按 TTFT、ITL、queue time 做扩缩容指标",
                    ],
                },
            ],
            "must_have_platform_controls": [
                "model gateway 统一鉴权、限流、审计和模型 allowlist",
                "按 short-context、long-context、agent-json 三类 workload 拆模型池",
                "请求 admission control：max input tokens、max output tokens、tenant QPS、并发槽位",
                "压测指标至少包含 TTFT、inter-token latency、p95/p99、GPU memory、KV cache hit、queue time",
            ],
        },
        {
            "id": "production_multi_agent_engineering",
            "question": "基于开源框架搭建生产级多智能体 Agent 系统，如何解决外部 API 依赖、多 Agent 任务争抢、对话上下文冗余膨胀三大工程难题？",
            "answer": "不要让多个 Agent 自由互调工具；用主链调度、typed action protocol、资源租约、上下文摘要和证据账本把开源 Agent 框架关进企业边界。",
            "solutions": [
                {
                    "problem": "外部 API 依赖",
                    "controls": [
                        "所有外部 API 经 tool gateway 代理，统一超时、重试、熔断、fallback、审计",
                        "依赖按 critical/optional 分级，optional API 失败只能降级，不能阻断主链",
                        "Web Search 仅作为补充证据，必须被 evidence arbiter 标记来源和冲突",
                        "为核心供应商准备 mock/sandbox contract tests，避免线上接口漂移",
                    ],
                },
                {
                    "problem": "多 Agent 任务争抢",
                    "controls": [
                        "任务进入 workflow executor/queue，Agent 只提交 action，不直接抢 GPU、文件或外部 API",
                        "用 resource lease 管理 GPU slot、repo clone slot、training slot、crawler slot",
                        "按 tenant/project/run_id 做公平队列和优先级，避免单个长任务占满资源",
                        "共享文件写入必须走 workspace guard 和 manifest，禁止 Agent 互相覆盖未知产物",
                    ],
                },
                {
                    "problem": "上下文冗余膨胀",
                    "controls": [
                        "每轮只给 context_digest，不回灌完整历史",
                        "RAG 片段带 path/line/token/score/source，按预算裁剪",
                        "长对话定期生成 decision summary、evidence summary、artifact summary 三类摘要",
                        "训练样本只从 evidence ledger 和高质量 manifest 选择，不从原始聊天硬抽",
                    ],
                },
            ],
            "recommended_stack": [
                "LangGraph/AutoGen/CrewAI 只作为局部编排库，不作为最终权限边界",
                "本项目保留 protocol.py/executor.py 作为唯一执行入口",
                "Kafka/Redis Stream 承载异步任务，PostgreSQL 保存 run/job/lease/audit",
                "OpenTelemetry 贯穿 Agent loop、tool gateway、model gateway 和 workflow executor",
            ],
        },
        {
            "id": "private_ai_platform_100_terminals",
            "question": "公司私有化 AI 平台要支撑 100+ 终端同时调用大模型、Agent、RAG 服务，如何从模型版本管理、灰度发布、服务弹性扩缩容三个角度设计？",
            "answer": "把模型、Agent workflow、RAG index 都当作可版本化生产资产，用网关路由和渐进发布控制风险，用 K8s/HPA/KEDA 和模型池隔离承载 100+ 终端并发。",
            "model_version_management": [
                "建立 model registry：base model、LoRA adapter、quantization、prompt template、eval score、owner、rollout stage",
                "模型版本用 semantic version + build hash；Agent workflow 和 RAG index 也必须版本化",
                "线上请求记录 model_version、workflow_version、rag_index_version，便于回放和事故定位",
                "新模型必须通过 action JSON 合法率、RAG 忠实度、延迟、成本和安全评测门禁",
            ],
            "gray_release": [
                "model gateway 支持按 tenant/user/percentage/header 路由到 candidate model",
                "Agent workflow 用 feature flag 开关，先影子流量，再小流量 canary",
                "RAG index 支持双索引：active/candidate，召回差异进入评估报告",
                "Argo Rollouts 做服务级 canary/blue-green，模型级灰度由 model gateway 控制",
            ],
            "elastic_scaling": [
                "Kubernetes 部署 API gateway、agent runtime、rag service、model gateway、model runtime 分层服务",
                "普通 API/RAG 服务用 HPA 按 CPU、QPS、p95 latency 扩缩",
                "模型服务按 queue depth、TTFT、GPU utilization、KV cache pressure 扩缩；GPU 节点用 Karpenter/Cluster Autoscaler",
                "高并发短请求和长上下文请求分池，避免长上下文拖垮 100+ 终端交互体验",
                "保留 local_production/小模型 fallback，主模型拥塞时允许降级处理非关键任务",
            ],
            "reference_capacity_start": {
                "terminals": "100+",
                "initial_pooling": ["2 replicas API gateway", "2-3 replicas agent runtime", "2 replicas RAG service", "1-2 GPU model pools"],
                "slo": ["interactive p95 < 8s for short agent step", "RAG retrieval p95 < 800ms", "model TTFT tracked per pool"],
            },
        },
    ]


def _phases(tier: str) -> list[dict[str, Any]]:
    return [
        {
            "phase": "foundation",
            "duration": "1-2 sprints",
            "outcomes": ["containerized app", "health probes", "model_runtime_status", "resource registry"],
        },
        {
            "phase": "enterprise_control",
            "duration": "2-4 sprints",
            "outcomes": ["OIDC/RBAC", "audit logs", "workflow executor", "canary deploy", "observability"],
        },
        {
            "phase": "factory_flywheel",
            "duration": "4-8 sprints",
            "outcomes": ["solution marketplace", "evidence-led training selection", "model router", "release dashboards"],
        },
        {
            "phase": "listed_company_hardening" if tier == "listed" else "scale_hardening",
            "duration": "ongoing",
            "outcomes": ["DR drill", "compliance evidence export", "multi-tenant isolation", "SLO/error budget governance"],
        },
    ]


def _decision_records(goal: str, tier: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "ADR-001",
            "title": "Use workflow contracts before visual canvas execution",
            "status": "accepted",
            "reason": "Enterprise hot iteration needs reviewable contracts, dry-run and rollback metadata.",
        },
        {
            "id": "ADR-002",
            "title": "Use OpenAI-compatible model runtime boundary",
            "status": "accepted",
            "reason": "vLLM, Transformers and future runtimes can be swapped without changing Agent chains.",
        },
        {
            "id": "ADR-003",
            "title": "Use progressive delivery for workflow/model changes",
            "status": "proposed" if tier != "listed" else "accepted",
            "reason": "Model and workflow behavior changes are product changes and need traffic shaping plus rollback.",
        },
        {
            "id": "ADR-004",
            "title": "Use Ray first for distributed execution, keep Spark/Flink in the data plane",
            "status": "accepted",
            "reason": "The platform's immediate scaling problem is distributed Python work orchestration; batch and streaming engines should be introduced by workload, not by fashion.",
        },
    ]


def build_enterprise_stack_plan(
    goal: str,
    workspace: Path,
    *,
    scale: str = "",
    regulated: bool = False,
    provider: str = "main_deepseek",
) -> dict[str, Any]:
    clean_goal = " ".join(str(goal or "").split())[:4000]
    tier = _scale_tier(clean_goal, scale)
    resources = discover_resources(workspace, type_filter="")
    provider_status = model_runtime_status(provider, probe=False)
    risk = _risk_profile(clean_goal, regulated)
    return {
        "schema": "enterprise_stack_plan.v1",
        "goal": clean_goal,
        "scale_tier": tier,
        "risk_profile": risk,
        "positioning": "上市企业级软件生产平台：主链治理、分链插件化、模型服务独立、发布可回滚、证据可审计。",
        "technology_choices": _technology_choices(clean_goal, tier),
        "scenario_solutions": _scenario_solutions(clean_goal, tier),
        "hot_iteration": _hot_iteration_strategy(tier),
        "model_plane": _model_plane(provider_status),
        "migration_phases": _phases(tier),
        "decision_records": _decision_records(clean_goal, tier),
        "resource_summary": resources.get("summary", {}),
        "keywords": sorted(_tokens(clean_goal))[:24],
    }
