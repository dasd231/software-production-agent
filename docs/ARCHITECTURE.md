# Architecture Overview

这份文档是 `software-production-agent` 的宏观地图：系统边界、运行链路、模块职责、稳定契约和主要扩展点都放在这里。README 负责快速上手，这里负责解释“为什么这样分层，以及以后从哪里改”。

## System Shape

项目是一个本地软件生产 Agent 骨架，核心思想是：

- `main.py` 负责 CLI 与模式分发。
- `agent/ui/app.py` 提供本地产品入口：一个需求输入框、几个模式选择、一个产出工作区。
- `agent/platform/api.py` 提供生产 ASGI 控制面；Flask UI 不作为上线承载。
- `agent_loop.py` 负责单次运行的闭环调度。
- `planner.py` 选择动态阶段，不写死流水线。
- `agent/decision/` 把 state/context/plan 转成候选动作分数、reward 和 trace，并用历史 reward 与 UCB bandit 重排下一轮候选动作。
- `agent/llm/providers.py` 统一 OPENAI/GROQ/DEEPSEEK 的 provider、model、API key env 和 OpenAI-compatible base_url。
- `agent/learning/` 提供 GitHub/Web/RAG/沙箱/学习资料构建 pipeline，和软件生产主循环解耦。
- `agent/evaluation/` 提供分链评价指标层，统一输出 `MetricReport`，避免把质量算法塞进链路编排文件。
- `agent/chains/registry.py` 提供分链能力目录，吸收 Coze Studio 的资源注册思想，但保持轻量 JSON/action 契约。
- `agent/intent/compiler.py` 把自然语言目标编译成可校验 workflow、dry-run 和资源建议。
- `agent/enterprise/stack.py` 把上市企业级技术选型、热迭代、模型服务和治理门禁输出为结构化方案。
- `agent/distributed/` 定义 contract-first 的分布式执行与数据面演进路线：Ray 先承接 Python 工作负载，Spark/Flink 按真实数据问题再引入。
- `agent/enterprise/maturity.py` 输出安全关键/工业级成熟度评估、CTO 拷问证据包和阶段路线。
- `agent/ui/auth.py` 提供本地用户、会话和 run 所属权限校验。
- `brain.py` 产出协议化 action。
- `protocol.py` 和 `executor.py` 负责 action 守门与执行。
- `ProjectState`、session JSONL、events JSONL 保存可恢复和可观测状态。
- `agent/chains/` 放主链可调用的分链入口；当前 `context` 分链统一注入 skills/RAG/MCP，`research` 分链统一做本地方案库/RAG/Web/LLM 综合，`training` 分链准备模型微调/SFT 数据集，`backup_model_training` 分链在质量门禁通过后生成备用本地模型训练任务，`github_crawler` 分链负责常规前后端项目爬取画像和方案沉淀，`solution_publish` 与 `evidence_ledger` 负责资产闭环。

```text
CLI / Product UI / env
  |
  v
agent.main / agent.ui.app
  |
  +-- inspect events/history -> agent.analytics.events_report
  |
  +-- local_production / llm
        |
        v
      agent.core.agent_loop
        |
        +-- workspace_index -> planner -> context sub-chain
        |                         |          |
        |                         |          +-- skills / unified RAG / MCP capabilities
        |                         |
        |                         v
        +-- decision policy -> candidate scores / reward / trace
        |
        +-- brain.decide/fix -> protocol -> executor -> tools/runtime/MCP
        |
        +-- ProjectState / SessionMemory / recorder events
```

## Runtime Flow

`run_agent_loop()` 是主控闭环：

1. 合并 `AppConfig` 与 `ExecutionLimits`。
2. 创建或恢复 `.agent_state.json`。
3. 生成单次运行 `run_id`，所有事件共用它。
4. 每轮同步工作区文件并构建 `workspace_index`。
5. Planner 选择下一阶段和任务。
6. `run_context_chain()` 注入 `skill_hints`、`rag_hints`、`mcp_capabilities`。
7. `decision.evaluate_decision_policy()` 生成特征、候选动作、分数和 reason。
8. Brain 根据 goal、plan、state、last_result、context_digest 产出 action JSON。
9. `protocol.py` 校验 action 结构，`executor.py` 再校验并分发到工具层。
10. `ProjectState.update_from_result()` 更新 progress、counters、last_result。
11. `decision.compute_reward_signal()` 和 `build_decision_trace()` 记录执行结果的算法反馈。
12. 质量/健康/安全门禁决定是否进入 fixing、investigate、ship 或 stopped。
13. recorder 写 `.agent_events.jsonl`，session 写 `.agent_session.jsonl`。

## Module Map

| Area | Files | Responsibility |
| --- | --- | --- |
| CLI | `agent/main.py` | 参数解析、env/CLI 配置合并、demo/LLM/inspect/history 分发、退出码 |
| Product UI | `agent/ui/app.py`, `agent/ui/offline_product.py`, `agent/ui/maturity.py` | Flask 本地产品壳，单输入框收集需求，只暴露 `local_production` 与 `llm` 两个产品模式，展示项目成熟度、用户产物、隔离预览、方案备份和 ZIP 下载；结果页支持基于上一版 run 的二次改进；本地生产按高成熟度 checklist 生成规格、契约、CRUD、测试、数据库设计、预览和 `solution_manifest.json` |
| Platform API | `agent/platform/api.py` | 生产控制面 FastAPI/ASGI：health/readiness、资源中心、第三方嵌入、模型运行时、意图编译、workflow dry-run、企业栈和工业成熟度 API；用 Gunicorn/Uvicorn 承载 |
| UI Auth | `agent/ui/auth.py` | 本地注册/登录/退出、PBKDF2 密码哈希、session 用户态、run owner/admin 权限校验 |
| Config | `agent/config.py` | 环境变量解析，形成不可变 `AppConfig` |
| LLM Provider | `agent/llm/providers.py`, `agent/llm/runtime.py` | OPENAI/GROQ/DEEPSEEK provider registry，前端模型列表，OpenAI-compatible client 创建；Model Plane 状态与 `/health`、`/v1/models` 探测 |
| Learning Pipeline | `agent/learning/*` | GitHub 搜索、repo 下载、过滤、README/结构解析、代码切片、向量库、知识卡、RAG QA、WebSearch、沙箱测试、最终编排 |
| Chains | `agent/chains/*` | 主链可调用的分链入口；分链只组合上下文/研究/学习等能力，不直接绕过协议执行工具 |
| Chain Registry | `agent/chains/registry.py` | 分链 action、schema、权限、成本、评价阶段的资源目录，可通过 `chain_registry` action 查询 |
| Resource Registry | `agent/resources/registry.py` | Coze-style 资源中心：分链、第三方 integration、模型 provider、知识库、方案库、训练集、run manifest 的统一发现 |
| Distributed Platform | `agent/distributed/*`, `agent/training/runners/ray_cluster.py` | contract-first 分布式执行面、Ray submission plan、distributed job manifest 与 Ray 训练 runner 骨架；不在普通检查路径启动集群 |
| Integration Fabric | `agent/integrations/embedding.py` | 第三方嵌入底座：外部系统 manifest、iframe/deeplink、安全沙箱、postMessage 桥、权限和资产映射计划 |
| Enterprise Stack | `agent/enterprise/stack.py` | 上市企业级技术选型、vLLM/SGLang 模型服务、多 Agent 工程治理、灰度发布和弹性扩缩容规划 |
| Industrial Maturity | `agent/enterprise/maturity.py` | 安全关键/工业级成熟度评分、CTO 拷问证据包、非协商门禁和 30/90/180/365 天路线 |
| Intent Compiler | `agent/intent/compiler.py` | 自然语言目标 -> `workflow.v1`、校验、dry-run、资源建议和风险提示 |
| Workflow Spec | `agent/workflows/spec.py`, `agent/workflows/dry_run.py` | 轻量 `workflow.v1` 校验与 dry-run：节点、边、拓扑排序、未知链路、环路、权限、联网、写文件、预期产物和门禁 |
| Loop | `agent/core/agent_loop.py` | 计划、决策、执行、反馈、修复、状态保存与事件写入 |
| Planner | `agent/core/planner.py` | 启发式或 LLM 动态阶段选择，失败场景进入 fixing/investigate |
| Decision | `agent/decision/*` | 候选动作打分、UCB bandit 选择器、reward、decision trace、policy state 更新、reward_avg 与 action value 反馈 |
| Brain | `agent/core/brain.py` | Demo brain 与 OpenAI brain；输出单行 action JSON |
| Protocol | `agent/core/protocol.py` | Pydantic action DTO，阻止未知 action/未知字段/错误 args |
| Governance | `agent/core/governance.py` | action 权限、风险级别、执行前确认与幂等元数据预检 |
| Executor | `agent/core/executor.py` | 唯一执行入口，二次校验、命令策略、timeout、输出裁剪、工具分发，并由 guarded path 返回标准错误码 |
| State | `agent/memory/project_state.py` | `.agent_state.json` schema、progress/counter/error/quality 更新 |
| Session | `agent/memory/session.py` | `.agent_session.jsonl` 会话审计与 prompt transcript 裁剪 |
| Context | `agent/context/*` | digest 与旧兼容入口；新增上下文来源优先接入 `agent/chains/context.py` |
| RAG | `agent/rag/local_index.py`, `agent/rag/unified.py` | 本地轻量检索与可选学习库融合检索 |
| Research | `agent/chains/research.py`, `agent/chains/research_cache.py`, `agent/chains/research_types.py` | 已验收正式方案库优先，方案库走关键词/向量/验收反馈混合检索；本地提取式请求带保守 L1/L2 缓存；研究链核心 payload 有显式类型契约 |
| Evidence | `agent/evidence/arbiter.py`, `agent/evidence/ledger.py` | 按 solution library -> local RAG -> Web 做证据仲裁；输出 conflict details / rationale / source confidence；证据账本汇总 manifest、评价、治理和 agent events |
| Training | `agent/chains/training.py`, `agent/chains/model_training.py` | 从 learning run 与方案库准备微调/SFT 数据集，输出 train/eval、质量报告、治理报告和训练计划；在门禁通过后生成备用本地模型训练 spec、版本清单和启动命令 |
| GitHub Crawler | `agent/chains/github_crawler.py` | GitHub/本地 repo 爬取画像，按可扩展架构规则打标签、质量评分，并将高质量项目导出为本地方案库 |
| Evaluation | `agent/evaluation/*` | 对 crawler/RAG/research/training 输出统一 `MetricReport`；`feedback.py` 将研究评分和方案验收沉淀为 JSONL 闭环日志、生成离线复盘报告，并为方案库排序提供 acceptance index |
| Innovation | `agent/innovation/radar.py` | 基于资源、工作流和评价产物生成创新雷达、差异化机会卡和推荐建设路线 |
| MCP-like | `agent/mcp/adapter.py` | 本地 MCP-like 工具目录与统一调用入口 |
| Tools | `agent/tools/*` | 文件、shell、git、workspace index 的低层能力 |
| Runtime | `agent/runtime/*` | shell runner、production check、chain run manifest |
| Solution Library | `agent/solution_library/manifest.py`, `agent/solution_library/publish.py` | `solution_manifest.v2` 标准化与发布；只有用户显式验收满意后的 run 才进入正式可复用方案资产 |
| Quality | `agent/pipeline/*` | 动态阶段枚举、review/health/wtf 启发式评分 |
| Observability | `agent/recorder.py`, `agent/observability.py` | 结构化事件、run_id/event_id、logger |
| Analytics | `agent/analytics/events_report.py` | 事件报告、baseline 对比、CI gate、history 趋势 |

## Stable Contracts

### Action Contract

Brain 只能输出：

```json
{"type":"action","action":"run_command","args":{"command":"python -m pytest -q","timeout":120}}
```

支持的 action 集合由 `agent/core/protocol.py` 的 `ALLOWED_ACTIONS` 管理。新增 action 时要同步：

- `ALLOWED_ACTIONS`
- `ActionDTO._args_shape()`
- `executor.run_action()`
- `agent/prompts/action.txt`
- README 的 Action 列表
- 对应 tests

`chain_registry` 是能力发现 action：它只返回注册信息，不执行分链。`resource_registry` 统一列出本地资源，`integration_catalog` / `integration_embed_plan` 把 Figma/GitHub/Notion 等外部系统规划成可嵌入、可审计、可沉淀资产的资源面。`workflow_validate` 只校验工作流 JSON。`intent_compile`、`workflow_dry_run`、`evidence_ledger`、`solution_publish` 组成意图到资产闭环：自然语言先变成可验证 workflow，再进入证据账本和方案资产库。分链真正运行仍由各自 action 进入 `protocol.py` 和 `executor.py`。

### Resource And Workflow Contracts

`resource_registry` 返回：

```json
{"schema":"resource_registry.v1","summary":{"total":0,"by_type":{}},"resources":[]}
```

它会发现 `integration`、`model_provider`、`model_runtime`、`model_pool` 和 `model_version` 等资源。`integration` 描述第三方嵌入 manifest、surface、capability、权限和 action 入口；`model_provider` 描述 provider 配置；`model_runtime` 描述本地 `main_deepseek` 这类 OpenAI-compatible endpoint；`model_pool` 描述 short/long/agent/training 模型池的并发、上下文和抢占策略；`model_version` 描述候选备用模型、基座、适配器和质量门禁结果。资源中心默认不做网络探测，保持只读且快速。

它也会发现 `distributed_backend`、`distributed_workload` 与 `distributed_platform_plan`。前者描述 `ray_cluster` 这类执行底座能力，中间者固定 learning/eval/promotion/training 等标准 workload 的 queue / priority / resource profile，后者把 Ray / Spark / Flink 放回各自正确的层：执行面、批数据面、流数据面。

`integration_embed_plan` 返回：

```json
{"schema":"integration_embed_plan.v1","integration":{},"surface":{},"bridge_contract":{},"permissions":{},"artifact_mapping":{},"admission":{}}
```

它用于第三方夸张嵌入：Figma 这类系统可作为 `embed_panel` 进入产品界面，也可作为 `resource_picker`、`action_bridge`、`webhook_event_source` 或 `asset_sync` 进入主链/分链。计划里显式返回 iframe sandbox、CSP、allowed origins、postMessage envelope、scope、secret env、数据策略和外部资产到本地方案库/RAG/训练集的映射。详见 `docs/THIRD_PARTY_EMBEDDING.md`。

`model_runtime_status` 返回：

```json
{"schema":"model_runtime_status.v1","provider":"main_deepseek","base_url":"http://127.0.0.1:8000/v1","probe":{"checked":true,"ok":true}}
```

它用于 Model Plane 健康检查：读取 provider/env 配置，可选探测 `/health` 与 `/v1/models`。主链不直接管理模型进程，vLLM、Transformers、未来 Ollama/llama.cpp 都只要暴露 OpenAI-compatible API 即可接入。

`model_route_plan` 返回：

```json
{"schema":"model_route_plan.v1","selected_pool":"long_pool","token_estimate":{},"queue_policy":{},"admission":{}}
```

它用于 Model Plane 准入：先估算 token 和业务类型，再选择 `short_pool`、`long_pool`、`agent_pool` 或 `training_batch_pool`，给出队列、租约、并发和拒绝/拆分建议。详见 `docs/MODEL_ROUTER_POOLS.md`。

`model_admission_acquire` 返回：

```json
{"schema":"model_admission.v1","admitted":true,"lease":{},"backpressure":{}}
```

它用于高并发承载：按池子发放 lease，池满返回 `pool_saturated` 和 429/backpressure，完成后用 `model_admission_release` 释放。默认 `local` backend 是单进程实现，多副本生产应替换为 Redis/队列后端。

`enterprise_stack_plan` 返回：

```json
{"schema":"enterprise_stack_plan.v1","technology_choices":[],"scenario_solutions":[],"hot_iteration":{}}
```

它面向上市企业级私有化落地，输出 vLLM/SGLang 技术选型、32K+ 长上下文优化、多 Agent 工程治理、100+ 终端模型版本/灰度/弹性方案。详见 `docs/ENTERPRISE_LANDING.md`。

`distributed_platform_plan` 返回：

```json
{"schema":"distributed_platform_plan.v1","planes":[],"adoption_order":[],"anti_patterns":[]}
```

它不做任何集群动作，只返回平台演进契约：Ray 先解决分布式执行，Spark 解决大规模批处理，Flink 只在真实实时状态问题出现后接入。详见 `docs/DISTRIBUTED_PLATFORM_ARCHITECTURE.md`。

`distributed_workload_catalog` 返回标准 workload 定义；`distributed_job_plan` 则返回 preview-only 的三件套：

```json
{"schema":"distributed_job_plan.v1","dispatch_mode":"preview_only","workload":{},"manifest":{},"submission":{}}
```

它们用于先把 queue、priority、resource profile 和产物契约审清楚，再决定是否真的接入执行后端。

`industrial_maturity_plan` 返回：

```json
{"schema":"industrial_maturity_plan.v1","overall":{},"dimensions":[],"cto_interrogation_pack":[]}
```

它面向安全关键/工业级 CTO 审查，输出成熟度评分、证据包、非协商门禁和阶段路线。详见 `docs/INDUSTRIAL_AI_CTO_MATURITY.md`。

`workflow_validate` 接收轻量 spec：

```json
{"schema":"workflow.v1","version":"demo","nodes":["research","training"],"edges":[["research","training"]]}
```

返回执行顺序、权限集合、是否需要联网/写文件，以及未知节点或环路错误。它不执行任何节点，只作为后续可视化编排和发布前校验。

`intent_compile` 返回：

```json
{"schema":"intent_compilation.v1","workflow":{},"validation":{},"dry_run":{},"resource_suggestions":[]}
```

它把用户目标编译成轻量 `workflow.v1`，同时给出标签、资源建议、风险提示和 dry-run。这个入口的定位不是“低代码画布”，而是“意图编译器”：先保证 workflow 合法、资源可发现、风险可解释，再进入执行。

`workflow_dry_run` 返回：

```json
{"schema":"workflow_dry_run.v1","execution_order":[],"nodes":[],"preflight_gates":[]}
```

它只读预演节点顺序、权限、联网/写文件风险、预期产物和前置门禁。

`evidence_ledger` 返回：

```json
{"schema":"evidence_ledger.v1","summary":{"total":0,"by_type":{}},"entries":[]}
```

它扫描 `run_manifest.json`、`solution_manifest.json`、`evaluation_report.json`、`governance_report.json` 和 `.agent_events.jsonl`，形成可搜索、可回放、可用于训练筛选的证据账本。

`solution_publish` 返回：

```json
{"schema":"solution_publish_result.v1","files":{},"manifest":{},"run_manifest":{}}
```

它把一次成功 run 发布成方案资产，写入 `solution_manifest.v2`、`docs/SOLUTION_BACKUP.md` 和发布链路 `run_manifest.json`。

`innovation_radar` 返回：

```json
{"schema":"innovation_radar.v1","north_star":"...","innovation_cards":[],"workflow_templates":[]}
```

它把资源中心、工作流模板和评价资产转成路线图，用于判断下一轮应该强化证据链、训练治理、方案资产化还是工作流平台化。

### Run Manifest Contract

会产生独立产物目录的分链需要写 `run_manifest.json`：

```json
{"schema":"run_manifest.v1","kind":"training_prepare","input":{},"files":{},"evaluation":{}}
```

manifest 记录输入摘要、产物路径、来源、风险和评价，供后续回放、训练筛选和资产库索引用。

### Event Contract

`.agent_events.jsonl` 每行至少包含：

```text
ts / kind / schema_version / event_id / run_id
```

常见 kind 的摘要字段：

- `plan`: `plan_summary`
- `context_enriched`: `summary`
- `decide` / `fix`: `action_summary` + `token_usage`
- `execute` / `execute_fix`: `result_summary` 中包含 `duration_ms`、`preflight_status`、`risk_level`，失败时包含 `error_code`、`retryable`、`recommended_action`
- `finish` / `stopped` / `ship_gate_blocked`: `result_summary`

事件报告消费这些摘要，不依赖完整大 payload。

### Decision Contract

Decision 层写入三类事件：

- `decision_policy`: 策略版本、strategy、features、candidate_actions、selected_action、reason
- `reward_signal`: action、ok、progress_before/after、components、total
- `decision_trace`: policy selected action、Brain selected action、alignment、reward_after_execution

`ProjectState.policy` 保存当前策略状态：

- `policy_version`
- `recent_strategy`
- `last_selected_action`
- `last_executed_action`
- `last_reward`
- `decision_count`
- `reward_total`
- `tool_success_stats`，其中 `reward_avg` 会反馈到下一轮 candidate score
- `action_value_estimates`，其中 `q/count` 会进入 UCB bandit 选择器
- `last_selector`，记录上一次选择器版本和 bandit 分数

硬边界：Decision 层不能执行工具，不能绕过 `protocol.py`、`executor.py`、ship gate 或 safety gate。

### State Contract

`.agent_state.json` 由 `ProjectState` 管理，关键字段：

- `goal`
- `files`
- `structure`
- `errors`
- `current_stage`
- `progress`
- `quality`
- `counters`
- `last_result`

字段迁移时保留 `schema_version`，并优先保持 `from_dict()` 对旧文件宽容。

## Data Flow

```text
Workspace files
  -> build_workspace_index()
  -> ProjectState.structure
  -> plan()
  -> run_context_chain()
       -> skill_hints
       -> rag_hints
       -> rag_observability
       -> mcp_capabilities
  -> evaluate_decision_policy()
       -> heuristic candidates
       -> policy memory adjustment
       -> UCB bandit ranking
       -> decision_policy
  -> build_context_digest()
  -> Brain payload
  -> Action JSON
  -> Protocol validation
  -> Executor result
  -> ProjectState.update_from_result()
  -> Chain evaluation metrics
  -> RewardSignal / DecisionTrace / PolicyState update
  -> Events/session/history reports
```

## Control Gates

| Gate | Location | Purpose |
| --- | --- | --- |
| Protocol gate | `core/protocol.py` | 拒绝未知 action、未知字段和错误 args |
| Governance gate | `core/governance.py` | 检查 required permissions、风险级别、显式确认和幂等元数据 |
| Executor gate | `core/executor.py` | 二次校验、命令策略、timeout、写入大小、输出裁剪，并统一输出 `VALIDATION_ERROR`、`PERMISSION_DENIED`、`CONFIRMATION_REQUIRED`、`POLICY_BLOCKED`、`TIMEOUT` 等错误码 |
| Fix safety gate | `core/agent_loop.py` | 失败过多或 wtf_likelihood 过高时停止 |
| Investigate escalation | `core/agent_loop.py`, `core/planner.py` | 连续命令失败后进入 evidence-first 排查 |
| Ship gate | `core/agent_loop.py` | finish 前要求最近验证成功且质量分达标 |
| Inspect gate | `analytics/events_report.py` | CI 中拦截 critical/worsened/context 退化 |
| History gate | `analytics/events_report.py` | CI 中拦截 passrate、duration、max_duration、regression 退化 |

## Product Modes

产品 UI 只保留两个用户模式：

```text
local_production
  -> heuristic Planner
  -> context sub-chain / decision policy
  -> OfflineProductBrain
  -> Protocol / Executor
  -> product artifacts + solution backup + preview

llm
  -> LLM Planner
  -> context sub-chain / decision policy
  -> OpenAIBrain through OPENAI/GROQ/DEEPSEEK
  -> Protocol / Executor
  -> product artifacts + events
```

Mode boundaries:

- `local_production` 不消耗 API，不生成 handoff 任务包，必须直接产出用户可见软件；
- `local_production` 会写 `docs/SOLUTION_BACKUP.md` 和 `solution_manifest.json`，后续方案检索从这里接；
- `llm` 是唯一 API 生产模式，OPENAI/GROQ/DEEPSEEK 只影响 Planner/Brain，执行仍由本地协议和执行器托管；
- 产品 UI 默认需要本地账号；run metadata 记录 `owner_user_id`，owner/admin 才可查看、下载、预览或二次改进；
- `frontend_sandbox`、`codex_handoff`、`llm_planner` 不再作为产品 UI 模式展示；
- 预览仍通过 CSP 和 iframe sandbox 服务生成产物的 `preview/index.html`，但没有独立“自定义前端沙盒”模式。

## Product Result Page

产品 UI 的结果页面向最终用户，不等同于 Agent 审计台。它只展示用户产物，并把系统账本留在工作区内部：

```text
run workspace
  -> .agent_state.json / .agent_events.jsonl / .agent_session.jsonl 供恢复与审计
  -> _list_run_files() 过滤内部账本和缓存
  -> build_maturity_report() 评估 README、前端、后端、依赖、测试、安全、预览和方案备份
  -> result page 展示成熟度、缺口、下一步建议、产物列表、文件预览、沙盒 iframe
  -> improve form 复制上一版用户产物到新 run，写入 docs/IMPROVEMENT_REQUEST.md
  -> download route 只打包用户产物
```

当前成熟度是启发式 checklist，不替代真实验收。后续可以把 `production_check`、测试覆盖、依赖审计、静态扫描、用户反馈和 `RewardSignal` 接入 `agent/ui/maturity.py`，让结果页从“结构成熟度”升级为“交付可信度”。

二次改进的边界：

- 只复制用户产物文件，不复制 `.agent_*` 内部状态、事件和会话账本；
- 新 run 写入 `source_run`、`base_goal` 和 `improvement_goal`，结果页展示 lineage；
- LLM 模式会在已复制的产物上继续生产；本地生产模式用于无 API 场景下直接跑完整产物链路；
- 后续可升级为 artifact diff、版本图谱、分支比较和一键回滚。

## Learning Pipeline

`agent/learning/` 是用于模型训练前置数据、RAG 知识库和项目学习的独立 pipeline。它不直接改软件生产主循环，也不执行下载仓库的任意脚本。

```text
GitHub Search / local repo
  -> repo downloader / local copier
  -> license/star/update filters
  -> README parser
  -> structure parser
  -> code slicer
  -> hashing vector index
  -> knowledge cards
  -> RAG extractive QA
  -> training_examples.jsonl export
  -> optional WebSearch supplemental links
  -> conservative sandbox checks
  -> orchestrator saves report/result/cards/vector index
```

Safety rules:

- network GitHub/Web steps are opt-in;
- downloaded repos are copied/cloned into `learning_runs` or the configured output directory;
- `.agent_*`, `.git`, dependency folders and caches are ignored before indexing/training material generation;
- sandbox default does not run project commands;
- Python syntax checks use in-memory `compile()` and do not create `__pycache__`;
- vector store is local JSONL by default, so replacing it with a real vector DB is a controlled extension point.
- training examples preserve citations back to repo/path/line metadata；
- learning runs now emit `slice_quality_report.json`、`card_quality_report.json`、`knowledge_quality_report.json`、`knowledge_promotion.json` and `quality_funnel.json` before publishing cards, vectors and training examples；
- only promoted knowledge assets enter the formal knowledge store and downstream training export；
- training preparation adds `sample_quality_report.json` and `sample_review.json` so fine-tuning examples are checked again before export；
- the thesis-grade extension of this mechanism is documented in `docs/KNOWLEDGE_QUALITY_CONTROL.md`.

## Extension Points

### Add a New Tool Action

1. 在 `protocol.py` 加 action 名和 args shape。
2. 在 `executor.py` 加分发逻辑。
3. 如果是外部能力，优先考虑接到 `mcp/adapter.py` 的 registry。
4. 在 `prompts/action.txt` 写清模型可用格式。
5. 补 `tests/test_protocol.py`、`tests/test_executor.py` 或 MCP 对应测试。
6. 更新 README Action 列表。

### Add a New Product Mode

1. 在 `agent/ui/app.py` 的 `ALLOWED_MODES` 增加 mode。
2. 在 `_build_config()` 映射该 mode 的配置差异。
3. 在 `_build_brain()` 映射该 mode 的 Brain 或策略 profile。
4. 保持 UI 层只选择模式，不直接执行工具。
5. 补 `tests/test_product_ui.py`，确保无 API Key 的路径仍可离线通过。

### Add a New Context Source

1. 在 `agent/chains/context.py` 注入新字段。
2. 在 `context/digest.py` 做裁剪，避免 Brain payload 过大。
3. 在 `agent_loop._plan_summary()` 或事件摘要中增加可观测信息。
4. 在 `events_report.py` 做汇总和 markdown/text/json 输出。
5. 增加 context pipeline 和 events tests。

### Add a New Resource Type

1. 在 `agent/resources/registry.py` 增加发现函数，输出稳定 `ResourceRecord`。
2. 资源发现必须只读，不能修改文件或执行项目脚本。
3. 新资源类型应在 `/resources` 页面和 `resource_registry` action 中自动可见。
4. 补 `tests/test_resource_workflow.py` 和必要的 UI/API 测试。

### Add a New Distributed Backend

1. 在 `agent/distributed/backends.py` 增加 contract-first backend 描述。
2. 如果它能执行训练，再在 `agent/training/runners/` 增加对应 runner。
3. 资源发现必须仍然只读，不能在 metadata 访问路径启动集群或占用重资源。
4. 如果新增后端会改变平台分层，再同步 `docs/DISTRIBUTED_PLATFORM_ARCHITECTURE.md` 与工作台 `platform_evolution`。
5. 补 `tests/test_distributed_platform.py`、`tests/test_training_platform.py` 和必要的 readiness 测试。

### Add a New Workflow Node Type

1. 优先把新能力注册到 `agent/chains/registry.py`，再由 `workflow_validate` 识别。
2. 工作流校验只验证 DAG、权限、联网、写文件等元信息，不执行真实 action。
3. 真正执行工作流前必须逐节点进入 `protocol.py` / `executor.py`。

### Add a New Innovation Bet

1. 在 `agent/innovation/radar.py` 增加 `InnovationCard`，包括 thesis、why_now、evidence、next_steps、impact、confidence。
2. 创新卡必须能从资源或评价状态中找到证据，不写纯口号。
3. 如果创新需要新分链，先加到 `chain_registry`，再补 workflow template。
4. 补 `tests/test_resource_workflow.py` 或 UI/API 测试。

### Add a New Research Source

1. 在 `agent/chains/research.py` 增加证据采集函数，输出可 JSON 序列化 evidence。
2. 保持本地方案库优先；外部 Web 只能补充，不能覆盖本地证据。
3. 新来源需要进入 `agent/evidence/arbiter.py` 的来源排序或冲突策略。
4. 如果进入 LLM 综合，prompt 必须要求引用 `[S]`、`[R]`、`[W]` 证据标签并允许证据不足时拒答。
5. 在 `core/protocol.py` 和 `core/executor.py` 只暴露稳定 action 参数，不把 provider 私有细节泄漏到 Brain。
6. 补 `tests/test_research_chain.py`、协议和执行器测试。

### Add a New Fine-tuning Source

1. 在 `agent/chains/training.py` 增加采集器，输出规范化 `instruction/input/output/citations/metadata`。
2. 样本必须可追溯；优先保留 citations、repo、path、line 或 solution backup 来源。
3. 训练数据进入正式导出前，先经过 `sample_quality_report.json` 对引用、重复、长度和任务多样性做二次审查。
4. `backup_model_train` 只在数据门禁、环境门禁和基座模型都满足时生成可启动任务；实际 rollout 前仍需人工模型评估。
5. 如果新增质量维度，优先扩展 `agent/evaluation/training.py` 或 `agent/evaluation/sample_quality.py`，不要把指标逻辑塞进采集器。
6. 如果新增治理维度，优先扩展 `agent/evaluation/governance.py`，并写入 `governance_report.json`。
7. 新格式导出需同时更新 `training_prepare` / `backup_model_train` action 参数校验和 tests。
8. 实际训练前必须人工检查隐私、密钥、许可证和样本质量。

### Add a New Crawl Architecture

1. 在 `agent/chains/github_crawler.py` 的 `ARCHITECTURE_RULES` 增加 `ArchitectureRule`。
2. 规则只描述文件标记、路径标记、内容标记和 tags，不直接把训练逻辑写进规则。
3. 新架构必须产出稳定 tags，供 `solution_manifest.json`、`training_prepare` 和检索复用。
4. 如果需要特殊质量项，扩展 `agent/evaluation/crawler.py`，并把 reason code 设计成稳定短字符串。
5. 导出的方案 manifest 走 `agent/solution_library/manifest.py`，保持 `schema_version` 和 `reuse_boundary` 稳定。
6. 补 `tests/test_github_crawler_chain.py`，覆盖架构识别、方案导出和训练分链接入。

### Add or Change Evaluation Metrics

1. 通用字段只改 `agent/evaluation/schemas.py`；链路指标分别放在 `crawler.py`、`rag.py`、`research.py`、`training.py`。
2. 每个指标输出稳定名称、原始 `value`、0-10 `score`、`weight`、`status` 和简短 `detail`。
3. 链路文件只调用 evaluator 并落盘/返回报告，不承载评分细节。
4. 需要兼容旧字段时保留旧 `quality` 摘要，同时把新指标放入 `evaluation`。
5. 补 `tests/test_evaluation_metrics.py` 和对应链路集成测试。

### Add or Replace a Decision Algorithm

1. 保持 `evaluate_decision_policy()` 返回 `policy_version/strategy/features/candidate_actions/selected_action/reason`。
2. 如果新增 reward 规则，保持 `compute_reward_signal()` 返回 `total/components/ok/action/progress_before/progress_after`。
3. 不要在 decision 层执行工具；真实执行仍必须由 Brain 输出 action 后进入 protocol/executor。
4. 在 `ProjectState.policy` 中只保存可序列化状态。
5. 更新 `events_report.py` 的 strategy/reward 汇总和对应 tests。

### Add a New CI Gate

1. 在 `events_report.py` 的 `should_fail_inspection()` 或 `should_fail_history()` 增加模式。
2. 在对应 `*_failure_reasons()` 返回稳定 reason code。
3. 在 `build_gate_result()` 或 `build_history_gate_result()` 输出机器可读字段。
4. 在 `main.py` argparse choices 增加模式。
5. 更新 README CLI 段和 tests。

## Testing Map

| Concern | Test Files |
| --- | --- |
| Action protocol | `tests/test_protocol.py` |
| Executor/tool dispatch | `tests/test_executor.py` |
| Main loop integration | `tests/test_integration_demo.py`, `tests/test_stage_flow.py` |
| Resume/safety/ship | `tests/test_resume.py`, `tests/test_safety_gate.py`, `tests/test_ship_gate.py` |
| Context/RAG/MCP | `tests/test_context_*.py`, `tests/test_mcp_adapter.py`, `tests/test_workspace_index.py` |
| Evaluation metrics | `tests/test_evaluation_metrics.py`, `tests/test_research_chain.py`, `tests/test_training_chain.py`, `tests/test_github_crawler_chain.py`, `tests/test_unified_rag.py` |
| Resource/workflow registry | `tests/test_resource_workflow.py`, `tests/test_executor.py`, `tests/test_protocol.py` |
| Innovation radar | `tests/test_resource_workflow.py`, `tests/test_product_ui.py` |
| UI auth | `tests/test_ui_auth.py`, `tests/test_product_ui.py` |
| Decision policy | `tests/test_decision_policy.py`, `tests/test_events_decide_summary.py` |
| Product UI | `tests/test_product_ui.py` |
| Learning pipeline | `tests/test_learning_pipeline.py` |
| Events and reports | `tests/test_events_*.py`, `tests/test_main_inspect_*.py` |
| History gates | `tests/test_history_report.py`, `tests/test_main_history_report.py` |
| Recorder contract | `tests/test_recorder.py`, `tests/test_event_schema_contract.py` |

## Operational Files

| File | Created By | Purpose |
| --- | --- | --- |
| `.agent_state.json` | `ProjectState.save()` | resumable agent state |
| `.agent_session.jsonl` | `SessionMemory.append_jsonl()` | recent conversation/session audit |
| `.agent_events.jsonl` | `recorder.append_event()` | structured machine-readable events |
| `.agent_users.json` | `LocalAuthStore` | local UI users, password hashes and permissions |
| `run_manifest.json` | chain-specific writers | reproducible chain input/files/evaluation/source_refs/risks |
| history JSONL | `--inspect-history` | append-only CI/quality trend rows |
| report sidecar `.meta.json` | `--inspect-save` | report provenance and SHA256 |

## Design Rules

- Keep `agent_loop.py` as the main chain orchestration, not business logic storage.
- Keep sub-chains under `agent/chains/`; they may enrich context or prepare decisions, but must not execute tools directly.
- Keep research synthesis local-first: solution library -> workspace/learning RAG -> Web -> LLM synthesis.
- Keep fine-tuning preparation auditable: collect -> normalize -> filter -> split -> export -> plan; actual training is explicit.
- Keep GitHub crawling extensible: architecture rules -> quality scoring -> solution export -> training ingestion.
- Keep `executor.py` as the only action execution gateway.
- Keep `agent/decision/` as scoring/reward/trace only; it must never execute tools.
- Keep `protocol.py` strict; tolerate model formatting noise before validation, not after.
- Add context through `agent/chains/context.py` and trim it through `context/digest.py`.
- Prefer structured event summaries over parsing large raw payloads.
- Preserve defensive defaults: failing observability must not break production work.
- When adding source files or major source edits, keep the file-level flowchart/improvement comment style.
