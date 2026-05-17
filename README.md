# 软件生产 Agent 系统（三源缝合）

本目录严格按仓库根目录 `AIread.md` 的架构与原则实现，与下列三个头部项目的关系如下（**不合并其源码**，只吸收角色分工与可执行契约）。

| 角色 | 来源 | 在本项目中的体现 |
|------|------|------------------|
| Agent 主控（Brain） | `everything-claude-code` | 会话记忆、系统提示组装、**主循环**与「计划→决策→执行→反馈→修复」闭环 |
| 执行层 Tool | `gstack` | **仅作工具语义**：`tools/file_tools.py`、`shell_tools.py` 提供受控文件与 shell，**不作为主框架** |
| 流程思想 | `ai-codegen-pipeline-` | `pipeline/stages.py`：**动态阶段**（非固定流水线），阶段由状态与 Planner 输出驱动 |
| 算法策略层 | 本项目新增 | `agent/decision/`：候选动作打分、reward、decision trace；只建议和记录，不绕过执行器 |

## 文档入口

| 文档 | 用途 |
|------|------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 宏观架构、运行链路、模块职责、稳定契约、扩展步骤、测试映射 |
| [`docs/KNOWLEDGE_QUALITY_CONTROL.md`](docs/KNOWLEDGE_QUALITY_CONTROL.md) | 论文级知识库质量控制框架、指标与门禁 |
| [`docs/BACKUP_MODEL_TRAINING.md`](docs/BACKUP_MODEL_TRAINING.md) | 高质量样本到备用本地模型训练任务的链路说明 |
| [`docs/TRAINING_ARCHITECTURE.md`](docs/TRAINING_ARCHITECTURE.md) | 本地控制面、Linux 执行面、数据快照和分布式扩展训练架构 |
| [`docs/DISTRIBUTED_PLATFORM_ARCHITECTURE.md`](docs/DISTRIBUTED_PLATFORM_ARCHITECTURE.md) | Ray-first 执行面、Spark/Flink 数据面与企业化演进路线 |
| [`docs/MODEL_EVALUATION.md`](docs/MODEL_EVALUATION.md) | 备用模型基座/adapter 对照评测 |
| [`research_workbench/README.md`](research_workbench/README.md) | 独立研究训练工作台：训练层级、指标、实验登记和论文阅读记录 |
| [`docs/THIRD_PARTY_EMBEDDING.md`](docs/THIRD_PARTY_EMBEDDING.md) | 第三方夸张嵌入能力：Figma/GitHub/Notion 等面板、资源选择器、动作桥和事件回流 |
| [`README.md`](README.md) | 快速启动、常用 CLI、环境变量、Action 和观测能力速查 |

## 目录结构

```
software-production-agent/
  README.md
  docs/
    ARCHITECTURE.md
  requirements.txt
  pyproject.toml
  agent/
    main.py
    config.py
    recorder.py
    observability.py
    chains/
      context.py
      registry.py
      research.py
      training.py
      github_crawler.py
    evidence/
      arbiter.py
    evaluation/
      schemas.py
      aggregate.py
      governance.py
      crawler.py
      training.py
      rag.py
      research.py
    innovation/
      radar.py
    integrations/
      embedding.py
    llm/
      providers.py
    learning/
      github_search.py
      repo_downloader.py
      filters.py
      readme_parser.py
      structure_parser.py
      code_slicer.py
      vector_store.py
      knowledge_cards.py
      rag_qa.py
      training_export.py
      store.py
      web_search.py
      sandbox.py
      orchestrator.py
      cli.py
    ui/
      app.py
      auth.py
    analytics/
      events_report.py
    context/
      digest.py
      enrichment.py
    core/
      agent_loop.py
      brain.py
      planner.py
      executor.py
      protocol.py
      feedback.py
    decision/
      policy.py
      reward.py
      trace.py
    mcp/
      adapter.py
    memory/
      session.py
      project_state.py
    pipeline/
      stages.py
      quality.py
    policies/
      default.json
      loader.py
    rag/
      local_index.py
      unified.py
    resources/
      registry.py
    scheduler/
      routing.py
    runtime/
      runner.py
      manifest.py
      production_check.py
    solution_library/
      manifest.py
    skills/
      router.py
    tools/
      file_tools.py
      shell_tools.py
      git_tools.py
      workspace_index.py
    workflows/
      spec.py
    prompts/
      system.txt
      planner.txt
      action.txt
  tests/
  workspace_demo/
```

## 运行

```bash
cd software-production-agent
pip install -r requirements.txt
# 离线验收闭环（无需 API Key）
python -m agent.main --demo

# 产品 UI 首次访问需要注册本地账号，首个账号自动为 admin
python -m agent.ui.app --host 127.0.0.1 --port 7860

# 使用 OpenAI 时（需环境变量 OPENAI_API_KEY）
python -m agent.main --llm --goal "写一个最小的 Flask 接口 /hello 返回 ok" --workspace ./workspace_demo

# 使用 DeepSeek 时（需环境变量 DEEPSEEK_API_KEY）
python -m agent.main --llm --provider deepseek --model deepseek-v4-flash --goal "写一个最小的 Flask 接口 /hello 返回 ok" --workspace ./workspace_demo

# Planner 也用 LLM（失败自动回退启发式）
python -m agent.main --llm --planner-llm --goal "..." --workspace ./ws

# 调试日志
python -m agent.main --demo -v

# 产品 UI：一个输入框 + 模式选择 -> 生成软件工作区
python -m agent.ui.app --host 127.0.0.1 --port 7860

# 学习/训练/RAG pipeline（本地 repo 离线可跑）
python -m agent.learning.cli --query "Flask agent RAG" --local-repo ./workspace_demo --output ./learning_runs/demo
```

`requirements.txt` 只安装基础控制面依赖。  
如果你需要在当前机器上部署模型服务，再显式安装：

```bash
pip install -r requirements-serving.txt
```

训练依赖继续单独使用 `requirements-training.txt`，不要和基础环境混装。

打开 `http://127.0.0.1:7860` 后，输入需求，只需要在两个产品模式中选择：`本地生产` 或 `LLM 生成`。本地生产不消耗 API Key，使用 Codex 代理的本地完整链路，仍会经过 Planner、Context、Decision Policy、Brain、Protocol、Executor、Feedback、State/Events，并直接产出软件；管理系统类需求会生成 backend/frontend/preview/docs/README、员工增删改查 Controller、参考数据接口、Vue CRUD 页面、前端 API 封装、后端 CRUD 测试、产品规格、API 契约、数据库设计、交付清单、静态可交互预览，以及 `docs/SOLUTION_BACKUP.md` / `solution_manifest.json` 方案备份。LLM 生成使用 OPENAI/GROQ/DEEPSEEK API，Planner 和 Brain 都走大模型链路；`OPENAI` 需要 `OPENAI_API_KEY`，`GROQ` 需要 `GROQ_API_KEY`，`DEEPSEEK` 需要 `DEEPSEEK_API_KEY`。结果页会展示项目成熟度、结构缺口、下一步建议、隔离预览和产物 ZIP 下载，也可以直接输入“基于此方案继续改进”，系统会复制上一版用户产物到新 run、写入 `docs/IMPROVEMENT_REQUEST.md` 并保留版本来源；结果页默认隐藏并排除 `.agent_*` 内部状态文件。

## 质量与旋钮（不计 token 的控质版本）

| 能力 | 说明 |
|------|------|
| **Pydantic 协议** | `agent/core/protocol.py`：`extra=forbid`、各 action 的 args 形状校验；模型输出可容错 ``` 围栏 |
| **执行器闸门** | 写盘 `max_write_bytes`、命令子串黑名单、timeout 上限/合法性校验、命令输出 head+tail 裁剪、`ExecutionLimits` 注入 |
| **Brain 拆分** | `agent/core/brain.py`：主循环薄；OpenAI 路径 `response_format=json_object` + 一次重试 |
| **Planner 双模** | `plan_heuristic` / `plan_with_openai` + LLM 失败回退；高失败场景会注入 `priority_guidance` 约束阶段选择 |
| **Skill 路由** | 每轮根据 `goal+stage+state` 产出 `skill_hints`（本地规则路由，最小可用） |
| **统一 RAG** | 每轮默认从工作区做轻量行级检索；配置 `AGENT_LEARNING_RAG_DIRS` 后会融合离线学习库 `vector_index.jsonl/knowledge_cards.json`，产出带来源、路径、行号、命中 token、置信度、文件大小与截断标记的 `rag_hints` |
| **研究综合分链** | `agent/chains/research.py`：本地 `solution_manifest.json` / `docs/SOLUTION_BACKUP.md` 方案库优先，融合工作区/学习库 RAG，可选 Web Search 补充和 LLM 生成带引用方案 |
| **微调训练分链** | `agent/chains/training.py`：从学习库 `training_examples.jsonl`、方案备份和内置 `action_protocol_sft` 协议样本生成 SFT 数据集，完成去重、样本质量复审、train/eval 切分、messages/alpaca 导出和 DeepSeek LoRA/QLoRA 训练计划 |
| **备用模型训练任务** | `agent/chains/model_training.py`：在数据质量、治理和环境门禁通过后生成备用本地模型训练 spec、标准 `training_job_spec`、job 生命周期清单、版本清单、启动命令和可审计 manifest |
| **备用模型评测** | `agent/evaluation/model_benchmark.py` + `agent/training/backup_eval.py`：从协议遵循、证据忠实和方案复用三个维度，对基座模型与 LoRA adapter 做可复现对照 |
| **GitHub 前后端爬取画像** | `agent/chains/github_crawler.py`：搜索/复制常规前后端项目，按可扩展架构规则识别 Spring/Vue、React、Node、Python API 等，打标签、质量评分，并把高质量项目导出成本地方案备份 |
| **MCP 适配层** | 提供 `mcp_capabilities` 与 `invoke_mcp_tool` 骨架，带参数归一化和结构化错误返回，可平滑扩展到真实 MCP |
| **LLM Provider** | `agent/llm/providers.py` 统一 OPENAI/GROQ/DEEPSEEK 的 API key、base_url、model 列表和 OpenAI-compatible client 创建 |
| **模型池路由** | `agent/scheduler/routing.py`：估算 prompt/output tokens，识别短请求、长上下文 RAG、Agent 工具调用和训练批处理，并输出 short/long/agent/training pool 准入计划，避免长上下文被短请求抢占 |
| **高并发准入** | `agent/scheduler/admission.py`：按模型池发放 lease、统计活动请求、池满返回 backpressure/429，调用结束释放或 TTL 自动回收 |
| **分布式平台路线** | `agent/distributed/`：先落 Ray contract-first 执行面，再按真实规模引入 Spark 批处理与 Flink 流处理；不在元数据检查路径上启动集群 |
| **学习/RAG Pipeline** | `agent/learning/` 覆盖 GitHub 搜索、repo 下载、license/star/update 过滤、README/结构解析、源码切片、向量化、知识卡、RAG QA、WebSearch 补充、沙箱测试和最终编排 |
| **生产验证** | `production_check` 自动执行 Python 编译检查和 pytest 目标检测，减少模型临场拼命令 |
| **算法策略层** | `agent/decision/` 将 context/state/plan 转成特征与候选动作分数，执行后生成 `RewardSignal` 和 `DecisionTrace`，并用 UCB bandit 对候选动作做探索/利用重排 |
| **产品 UI** | `agent/ui/app.py` 提供本地 Flask 产品壳：单需求输入框、两个产品模式、运行工作区、项目成熟度、隔离预览和产物下载；`agent/ui/offline_product.py` 承担本地生产 Brain，按高成熟度 checklist 生成规格、契约、CRUD、测试、数据库设计、预览和方案备份；`agent/ui/maturity.py` 给结果页生成启发式成熟度报告 |
| **可观测** | `agent/observability.py` + 循环 INFO；`agent/recorder.py` 写入带 `event_id/run_id` 的结构化事件；`SessionMemory.append_jsonl` 审计尾部会话 |
| **事件摘要** | 事件 JSONL 每行含 `schema_version=1` 与 `event_id/run_id`；`context_enriched` 提供上下文注入摘要（含 RAG 路径与截断数）；`plan` 附带 `plan_summary`，`decide/fix` 附带 `action_summary`，`execute/execute_fix/finish/stopped/ship_gate_blocked` 附带 `result_summary` |
| **状态版本** | `ProjectState.schema_version` 便于以后迁移 |
| **升级协议** | 连续失败进入 `investigate`，并以 `stopped:investigate_required` 明确停机；同时写入 `state.structure.investigate_handoff`，且 `planner` 会把推荐动作注入 `investigate` 阶段任务 |

### 环境变量（可选）

| 变量 | 含义 |
|------|------|
| `AGENT_MAX_ITERATIONS` | 最大主循环轮数（默认 48） |
| `AGENT_MAX_WRITE_BYTES` | 单次 `write_file` 上限（默认 1_500_000） |
| `AGENT_CMD_TIMEOUT` | 默认 shell 超时秒（默认 120） |
| `AGENT_CMD_MAX_TIMEOUT` | 单次命令 timeout 上限（默认 600） |
| `AGENT_CMD_MAX_OUTPUT_CHARS` | 单路 stdout/stderr 裁剪上限，采用 head+tail 保留（默认 200_000） |
| `AGENT_LLM_PROVIDER` | 默认 LLM provider：`openai` 或 `groq`（默认 `openai`） |
| `AGENT_PLANNER_LLM` | `1` 时 Planner 走 OpenAI（等价 `--planner-llm`） |
| `OPENAI_BRAIN_MODEL` / `OPENAI_PLANNER_MODEL` | 模型 id |
| `GROQ_API_KEY` | Groq API key，配合前端选择 `GROQ` 使用 |
| `DEEPSEEK_API_KEY` | DeepSeek API key，配合前端选择 `DEEPSEEK` 使用 |
| `AGENT_SESSION_LOG` | `0` 关闭 `.agent_session.jsonl` 追加 |
| `AGENT_VERBOSE` | `1` 时 DEBUG 日志 |
| `AGENT_POLICY_JSON` | 额外 `forbidden_substrings` 策略文件（JSON），与内置及 `agent/policies/default.json` 合并 |
| `AGENT_EVENTS_LOG` | `1` 时写入 `.agent_events.jsonl`（等价 `--events`） |
| `AGENT_RESUME_CLEAR_ERRORS` | `1` 时在 `--resume` 下启动清空 `state.errors` |
| `AGENT_SHIP_MIN_REVIEW_SCORE` | `ship` 门禁最低 review 分（默认 `6.0`） |
| `AGENT_SHIP_MIN_HEALTH_SCORE` | `ship` 门禁最低 health 分（默认 `7.0`） |
| `AGENT_ENABLE_SKILL_HINTS` | 是否启用 skill hints 注入（默认 `1`） |
| `AGENT_ENABLE_RAG_HINTS` | 是否启用本地 rag hints 注入（默认 `1`） |
| `AGENT_ENABLE_MCP_CAPABILITIES` | 是否注入 mcp capability 目录（默认 `1`） |
| `AGENT_SKILL_HINTS_LIMIT` | 每轮 skill hints 数量上限（默认 `4`） |
| `AGENT_RAG_HINTS_TOP_K` | 每轮 rag hints 召回上限（默认 `3`） |
| `AGENT_ENABLE_LEARNING_RAG` | 是否启用离线学习库 RAG；默认在 `AGENT_LEARNING_RAG_DIRS` 非空时自动启用 |
| `AGENT_LEARNING_RAG_DIRS` | 一个或多个学习链路 output 目录，Windows 用 `;` 分隔；目录内需有 `vector_index.jsonl` 和 `knowledge_cards.json` |
| `AGENT_LEARNING_RAG_TOP_K` | 每个学习库额外召回片段数（默认 `2`） |
| `AGENT_LEARNING_RAG_BM25` | 学习库补充召回是否启用 BM25/RRF 融合（默认 `1`） |
| `MODEL_SHORT_BASE_URL` | `short_pool` OpenAI-compatible endpoint（默认 `http://model-vllm-short:8000/v1`） |
| `MODEL_LONG_BASE_URL` | `long_pool` OpenAI-compatible endpoint（默认 `http://model-vllm-long:8000/v1`） |
| `MODEL_AGENT_BASE_URL` | `agent_pool` OpenAI-compatible endpoint（默认 `http://model-agent:8000/v1`） |
| `MODEL_BATCH_BASE_URL` | `training_batch_pool` endpoint（默认 `http://model-batch:8000/v1`） |
| `MODEL_ADMISSION_BACKEND` | 模型准入租约后端；当前 `local`，多副本生产建议替换为 Redis/队列 |
| `MODEL_SHORT_POOL_MAX_CONCURRENCY` | `short_pool` 在线并发上限（默认 128） |
| `MODEL_LONG_POOL_MAX_CONCURRENCY` | `long_pool` 在线并发上限（默认 8） |
| `MODEL_AGENT_POOL_MAX_CONCURRENCY` | `agent_pool` 在线并发上限（默认 32） |
| `MODEL_TRAINING_BATCH_POOL_MAX_CONCURRENCY` | `training_batch_pool` 在线并发上限（默认 4） |

也可以在项目根目录创建本地密钥文件 `.env.local`，项目启动时会自动读取，且该文件已被 `.gitignore` 忽略：

```text
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk-...
DEEPSEEK_API_KEY=sk-...
AGENT_LLM_PROVIDER=openai
OPENAI_BRAIN_MODEL=gpt-4o-mini
OPENAI_PLANNER_MODEL=gpt-4o-mini
```

系统环境变量优先级更高；`.env.local` 只补充当前进程缺失的变量。

### 新增 Action

- **`git_status`**：工作区内 `git status --porcelain` 文本结果。  
- **`git_init`**：若无 `.git` 则 `git init`；已存在则 `already_git_repo`。失败时 `ok:false` 会进入修复轮。
- **`workspace_index`**：返回轻量工作区索引（文件、语言、入口、测试文件），帮助 Brain 做上下文决策。
- **`mcp_capabilities`**：返回 MCP 能力目录（可用工具清单与 `args_schema`），便于后续精确选择 `mcp_call`。
- **`mcp_call`**：统一调用 MCP 适配工具（如 `workspace.search`、`workspace.read`、`workspace.list`、`git.status`）。
- **`production_check`**：运行本地生产验证（Python `py_compile`，检测到 pytest 目标时运行 `python -m pytest -q`）。
- **`web_search`**：使用 DuckDuckGo Instant Answer API 进行网络搜索，查询外部知识与 API 文档（详见 [`docs/WEBSEARCH_INTEGRATION.md`](docs/WEBSEARCH_INTEGRATION.md)）。
- **`chain_registry`**：查询可用分链、输入输出 schema、权限、成本等级和评价阶段，借鉴 Coze Studio 的资源注册/能力目录思路。
- **`resource_registry`**：统一列出分链、模型 provider、本地知识库、方案库、训练集和 run manifest，支撑“资源中心”页面。
- **`integration_catalog` / `integration_embed_plan`**：第三方嵌入底座；把 Figma/GitHub/Notion/Linear/Slack 等外部系统规划成嵌入面板、资源选择器、动作桥、事件源和资产同步链路，并返回安全沙箱、postMessage 合约、权限与资产映射。
- **`model_runtime_status`**：查看 `main_deepseek` / OpenAI-compatible 模型服务的 base_url、模型、API key 状态，并可探测 `/health` 与 `/v1/models`。
- **`model_route_plan`**：先估算 prompt/output tokens、判断业务类型，再选择 `short_pool` / `long_pool` / `agent_pool` / `training_batch_pool`，返回准入和队列策略，避免上下文池互相抢占。
- **`model_admission_status` / `model_admission_acquire` / `model_admission_release` / `model_admission_renew`**：模型池高并发租约；请求拿到 lease 才能进入模型网关，池满返回 backpressure。
- **`enterprise_stack_plan`**：面向上市企业/私有化场景输出技术选型、热迭代、vLLM/SGLang 模型服务、多 Agent 工程治理、100+ 终端弹性和灰度方案。
- **`distributed_platform_plan` / `distributed_workload_catalog` / `distributed_job_plan`**：查看 Ray-first / Spark-later / Flink-when-needed 平台路线、标准 workload 目录，并在不派发任务的前提下预览分布式 job manifest 与 Ray submission contract。
- **`industrial_maturity_plan`**：面向安全关键/工业级 CTO 审查输出成熟度评分、证据包、非协商门禁和 30/90/180/365 天路线。
- **`enterprise_readiness_check`**：运行企业上线静态门禁，检查 FastAPI/ASGI、vLLM/SGLang、非 Flask/Ollama、K8s、HPA、PDB、NetworkPolicy、CI 和文档基线。
- **`workflow_validate`**：校验轻量 `workflow.v1` JSON 的节点、边、未知分链、环路、权限和是否联网/写文件；只校验，不执行。
- **`innovation_radar`**：读取资源中心、工作流模板和评价资产，生成项目创新雷达、差异化机会卡、平台评分和推荐建设路线。
- **`intent_compile`**：把自然语言目标编译成 `workflow.v1`，同时返回校验、dry-run、资源建议和风险提示，是替代低代码画布的“意图入口”。
- **`workflow_dry_run`**：只读预演 workflow，展示执行顺序、权限、联网/写文件风险、预期产物和前置门禁。
- **`evidence_ledger`**：汇总 `run_manifest.json`、`solution_manifest.json`、评价报告、治理报告和 agent events，生成可检索的证据账本。
- **`solution_publish`**：把当前 run 发布为本地方案资产，落盘 `solution_manifest.v2`、`docs/SOLUTION_BACKUP.md` 和发布链路 `run_manifest.json`。
- **`research_synthesize`**：本地方案库 + 本地/学习库 RAG + 可选 Web Search + 可选 LLM 综合；返回 `evaluation`，评价方案命中、RAG 命中、Web 补充、引用覆盖和本地优先度。
- **`training_prepare`**：准备模型微调/SFT 数据集与训练计划；默认注入动作协议专项样本，单独训练模型输出严格 action JSON；只写入数据文件和报告，不启动实际 GPU 训练；返回 `evaluation`、`governance`、`evaluation_summary` 并落盘 `run_manifest.json`。
- **`backup_model_train`**：读取已审查训练集，复核数据门禁与训练环境，生成备用本地模型训练任务、版本清单、启动命令和 `run_manifest.json`；门禁未通过时明确阻塞而不是假装可训练。
- **`github_crawl_profile`**：爬取或画像 GitHub/本地常规前后端项目，输出架构标签、质量分、训练标签和 `evaluation`，并将高质量项目导出为本地 `solution_manifest.json` / `SOLUTION_BACKUP.md` 与 `run_manifest.json`。

这轮开始把项目推进为“意图到生产”的 AgentOS：自然语言目标先编译为可验证 workflow，再进入证据账本和方案资产闭环。路线详见 [`docs/INTENT_AGENTOS.md`](docs/INTENT_AGENTOS.md)。

企业级落地方案详见 [`docs/ENTERPRISE_LANDING.md`](docs/ENTERPRISE_LANDING.md)：覆盖 vLLM/SGLang 技术选型、32K+ 长上下文、高并发 API、多 Agent 资源争抢、上下文膨胀、模型版本管理、灰度发布和弹性扩缩容。

模型池路由详见 [`docs/MODEL_ROUTER_POOLS.md`](docs/MODEL_ROUTER_POOLS.md)：覆盖 Token Estimator、short/long/agent/training pool、准入、隔离队列和抢占规避。

第三方嵌入底座详见 [`docs/THIRD_PARTY_EMBEDDING.md`](docs/THIRD_PARTY_EMBEDDING.md)：覆盖 Figma 式嵌入面板、资源选择器、动作桥、事件回流、权限隔离和资产沉淀。

安全关键/工业级 CTO 成熟度路线详见 [`docs/INDUSTRIAL_AI_CTO_MATURITY.md`](docs/INDUSTRIAL_AI_CTO_MATURITY.md)：覆盖成熟度等级、CTO 拷问证据包、非协商门禁和阶段路线。

### 上线承载 / Production Serving

生产承载不走 Flask，也不把 Ollama 当模型服务面：

- `agent/ui/app.py` 的 Flask 只作为本地操作 UI 和演示入口。
- 生产控制面使用 FastAPI/ASGI：`agent/platform/api.py`。
- 平台进程使用 Gunicorn + UvicornWorker：`deploy/production/Dockerfile.platform`。
- 模型服务默认走 vLLM/SGLang/OpenAI-compatible endpoint；`Ollama` 只适合开发便捷性，不作为本项目生产承载。
- 部署样例见 [`deploy/production/README.md`](deploy/production/README.md)，包含 Docker Compose、Kubernetes Deployment、Service 和 HPA。

本地启动生产 API 面：

```bash
python -m agent.platform.api --host 0.0.0.0 --port 8080 --runs-root ./product_runs
curl http://127.0.0.1:8080/healthz
```

容器化：

```bash
docker compose -f deploy/production/docker-compose.yml up --build platform-api
docker compose -f deploy/production/docker-compose.yml --profile model up --build
```

上线整改门禁：

```json
{"type":"action","action":"enterprise_readiness_check","args":{}}
```

### 上下文增强（每轮自动）

- `state.structure.skill_hints`：技能建议（如 API 开发、调试、测试、发布门禁）
- `state.structure.rag_hints`：统一检索片段（本地工作区优先；可融合离线学习库，按 goal、当前任务与最近错误信息召回）
- `state.structure.rag_observability`：RAG 来源、命中数、学习库加载状态、耗时、降级错误摘要和统一检索评价指标
- `state.structure.mcp_capabilities`：当前 MCP 适配能力目录
- Brain 用户负载中会生成 `context_digest`（结构化裁剪后的 hints/capabilities，RAG 保留路径、行号、命中 token 与大小/截断元数据，并在 `summary` 中标注原始数量、纳入数量、遗漏数量和截断片段数），用于直接引导下一步动作决策。
- `state.structure.decision_policy`：策略层候选动作打分与理由，会进入 `context_digest`，供 Brain 参考但不强制执行。
- Planner 输入同样会包含结构化 `context_digest`；在连续失败场景还会追加 `debug_capability_hints`，帮助优先选择可执行排查路径。
- 启发式 Planner 也会把 context 转为任务文本：在 `coding/fixing/investigate` 阶段自动附加 `rag_hints/skill_hints/mcp` 引导，减少盲目试错。

### 算法策略层

当前第一版算法层位于 `agent/decision/`：

- `policy.py`：把 `ProjectState + plan + context` 转成特征，输出 candidate actions、score 和 reason，并用 `tool_success_stats.reward_avg` 微调下一轮动作分。
- `bandit.py`：把 heuristic score、`action_value_estimates.q` 和 UCB exploration bonus 合成 `bandit_score`，在不执行工具的前提下重排候选动作。
- `reward.py`：根据执行前后状态和 result 计算启发式 reward。
- `trace.py`：记录 policy 建议、Brain 实际 action、alignment 和 reward。

`ProjectState.policy` 会保存每个 action 的尝试次数、reward 均值和增量价值估计。硬边界：算法层只能建议、打分、记录和更新 `ProjectState.policy`；所有真实执行仍必须经过 `protocol.py` 和 `executor.py`。

### 产品模式

用户侧只保留两个模式：

- `本地生产`：不消耗 API，使用本地 Brain 走完整工业链路并直接生成产物；同时写入 `docs/SOLUTION_BACKUP.md` 和 `solution_manifest.json`，为后续方案检索做准备。
- `LLM 生成`：使用 OPENAI/GROQ/DEEPSEEK API，Planner 和 Brain 都由大模型参与，执行仍必须经过协议、执行器和安全门禁。

历史上的 demo、前端沙盒、Codex handoff 不再作为产品入口展示。隔离预览能力仍用于展示生成产物的 `preview/index.html`，但不再提供单独的“自定义前端沙盒”模式。

### 账号与权限

产品 UI 已具备本地注册、登录、退出和 run 所属用户校验：

- 用户数据保存在 runs root 下的 `.agent_users.json`；密码使用 PBKDF2-HMAC-SHA256 加盐哈希。
- 首个注册用户自动成为 `admin`，后续用户为普通 `user`。
- `/`、`/run`、`/runs/<id>`、文件、下载和预览都需要登录。
- run metadata 会记录 `owner_user_id`；非 owner 不能访问，admin 可访问所有 run。
- `/resources` 是本地资源中心，聚合模型、分链、知识库、方案库、训练数据和 run manifest。
- `/innovation` 是创新雷达，输出平台定位、创新机会卡、推荐工作流和下一步建设方向。

### 资源与工作流

借鉴 Coze Studio 的资源管理/工作流思想，但保持轻量 JSON 边界：

- `agent/resources/registry.py`：发现 chain、model_provider、knowledge_store、solution、training_dataset、run_manifest。
- `agent/workflows/spec.py`：校验 workflow 节点和边，给出执行顺序、权限集合、是否需要联网、是否写文件。
- `agent/innovation/radar.py`：把资源状态转成创新路线图，突出证据操作系统、软件工厂飞轮、可治理微调和工作流优先平台。
- 资源中心只读展示，不绕过 `protocol.py` / `executor.py`；真正执行仍必须走 action。

### 创新抓手

当前最值得打的差异化方向：

- **Evidence Ledger**：每个回答和产物都能追溯到 `[S]/[R]/[W]` 证据和 run manifest。
- **Software Factory Flywheel**：生成产物沉淀为方案资产，再进入 RAG、训练和下一轮生成。
- **Governed Fine-tuning**：训练数据不只是导出 JSONL，而是带引用、治理、风险和可回放账本。
- **Workflow-first Agent Studio**：先有可验证 JSON 工作流，再做可视化画布，保证平台可控。

### 学习 / 训练 / RAG Pipeline

`agent/learning/` 是一条独立的学习资料构建链路，先保持和软件生产主循环解耦：

| Step | 文件 | 当前实现 |
|------|------|----------|
| 1. GitHub 项目搜索器 | `github_search.py` | GitHub Search API client，支持 `GITHUB_TOKEN` |
| 2. Repo 下载器 | `repo_downloader.py` | `git clone --depth 1` 或本地 repo copy |
| 3. License / Star / 更新时间筛选器 | `filters.py` | SPDX、stars、updated_after 过滤 |
| 4. README 解析器 | `readme_parser.py` | 标题、摘要、章节规则解析 |
| 5. 项目目录结构解析器 | `structure_parser.py` | 语言、入口、测试、包文件、目录 |
| 6. 源码切片器 | `code_slicer.py` | 按行窗口切片，带 token 去重 |
| 7. 向量化入库 | `vector_store.py` | 无依赖 hashing vector + JSONL 持久化 |
| 8. 知识卡片生成器 | `knowledge_cards.py` | overview/setup/architecture/code cards |
| 9. RAG 检索问答 | `rag_qa.py`, `store.py` | 本地抽取式回答，带代码 evidence；支持对已有学习库 `--ask` |
| 10. Web Search 补充学习 | `web_search.py` | DuckDuckGo IA + fallback links |
| 11. 沙箱运行测试 | `sandbox.py` | 静态大小检查 + Python 内存 compile；默认不执行 repo 脚本 |
| 12. Agent 编排 | `orchestrator.py` | 串联所有步骤并落盘 report/result/vector/cards |
| 训练样本导出 | `training_export.py` | 从知识卡、代码片段和 RAG answer 导出可追溯 JSONL 样本 |

学习链路会忽略 `.agent_*`、`.git`、`node_modules`、虚拟环境和缓存目录，避免把运行状态或噪音文件混进训练/RAG 材料。

本地离线运行：

```bash
python -m agent.learning.cli --query "Flask agent RAG" --local-repo ./workspace_demo --output ./learning_runs/demo
```

把已有学习库接入 Agent 主循环：

```bash
set AGENT_LEARNING_RAG_DIRS=./learning_runs/demo
python -m agent.main --demo --goal "基于学习库实现 hello route" --workspace ./workspace_demo
```

对已有学习库提问：

```bash
python -m agent.learning.cli --output ./learning_runs/demo --ask "hello route 在哪里"
```

联网搜索 GitHub / Web 时显式打开：

```bash
python -m agent.learning.cli --query "agent rag framework language:python" --github --web --repo-limit 3 --output ./learning_runs/github-rag
```

当前“模型训练”默认不直接训练大模型，而是产出可复用的 `knowledge_cards.json`、`vector_index.jsonl`、`training_examples.jsonl`、`answers.jsonl`、`report.md` 和后续可转 SFT/RAG eval 的结构化材料。

如果你希望补强 grounded-answer 训练切片，学习链可以显式导出多条 RAG 训练查询：

```bash
python -m agent.learning.cli `
  --query "员工管理系统" `
  --local-repo ./workspace_demo `
  --training-rag-query "新增员工接口是什么" `
  --training-rag-query "项目如何启动" `
  --training-rag-query-limit 8 `
  --output ./learning_runs/demo-rich-grounding
```

超过显式查询后，系统会继续从知识卡问题中补足到上限，用于避免 `rag_grounded_answer` 在训练集中长期只有极少样本。

微调数据准备分链：

```json
{"type":"action","action":"training_prepare","args":{"output_dir":"./training_runs/demo","learning_dirs":["./learning_runs/demo"],"solution_dirs":["./product_runs"],"dataset_format":"messages","eval_ratio":0.15,"model_hint":"deepseek-coder","include_protocol_examples":true}}
```

GitHub / 本地前后端爬取画像：

```json
{"type":"action","action":"github_crawl_profile","args":{"query":"spring boot vue management system","output_dir":"./crawl_runs/fullstack","github":true,"repo_limit":5,"min_stars":100,"allowed_licenses":["MIT","Apache-2.0"],"quality_threshold":6.5}}
```

离线调试可以用本地仓库：

```json
{"type":"action","action":"github_crawl_profile","args":{"output_dir":"./crawl_runs/local","github":false,"local_repos":["./workspace_demo"],"repo_limit":1,"min_stars":0,"quality_threshold":0}}
```

输出的 `crawl_runs/*/solutions` 可以直接进入微调分链：

```json
{"type":"action","action":"training_prepare","args":{"output_dir":"./training_runs/from-crawl","solution_dirs":["./crawl_runs/fullstack/solutions"],"dataset_format":"messages","eval_ratio":0.15,"model_hint":"deepseek-coder"}}
```

输出包含：

- `dataset.jsonl`：完整 SFT 数据集
- `train.jsonl` / `eval.jsonl`：确定性切分
- `raw_examples.jsonl`：规范化后的原始样本
- `protocol_examples.jsonl`：严格 action JSON 协议样本
- `dataset_snapshot_manifest.json`：训练数据冻结快照、来源、任务配比、内容 hash 和 shard manifest
- `quality_report.json`：任务类型、引用率、拒绝原因
- `sample_quality_report.json` / `sample_review.json`：训练样本二次审查结果，记录引用、重复、长度与拒绝原因
- `evaluation_report.json`：样本量、引用率、任务多样性、拒绝率、格式合法性和 train/eval 切分质量
- `governance_report.json`：密钥/隐私风险代理扫描、引用率、重复率、人工复核门禁
- `evaluation_summary.json`：训练质量与治理指标聚合
- `run_manifest.json`：输入、来源、产物、评价、风险和可追踪 manifest
- `training_plan.json`：DeepSeek LoRA/QLoRA 训练建议与下一步
- `report.md`：人工审查摘要

备用本地模型训练任务：

```json
{"type":"action","action":"backup_model_train","args":{"training_dir":"./training_runs/demo","output_dir":"./model_runs/backup-demo","base_model":"deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B","adapter_name":"backup-local-lora","launch":false,"min_quality_score":6.5,"min_train_examples":20}}
```

该动作会输出 `backup_training_spec.json`、`training_job_spec.json`、`training_job_manifest.json`、`training_environment.json`、`data_gate.json`、`model_version_manifest.json`、`launch_command.txt` 和 `run_manifest.json`。如果样本质量不足、治理未通过、依赖缺失、CUDA 不可用或未指定基座模型，状态会直接落为 `blocked_*`，不会把“可以训练”伪装成“已经具备训练条件”。真正开训仍需显式执行：

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\setup_training_env.ps1
.\.venv-train\Scripts\python.exe -m agent.training.backup_trainer --config ./model_runs/backup-demo/backup_training_spec.json --dry-run
.\.venv-train\Scripts\python.exe -m agent.training.backup_trainer --config ./model_runs/backup-demo/backup_training_spec.json
```

训练完成并评测后，可以再生成一个保守的晋级门禁产物：

```bash
.\.venv-train\Scripts\python.exe -m agent.training.promotion `
  --baseline-report ./model_evals/base/model_evaluation_report.json `
  --candidate-report ./model_evals/tuned/model_evaluation_report.json `
  --model-version-manifest ./model_runs/backup-demo/model_version_manifest.json `
  --output-dir ./model_evals/tuned
```

它会生成 `model_promotion_decision.json` 和 `promotion_report.md`，用于判断候选模型是否达到“进入人工评审”的标准，而不是自动替换主模型。

如果你需要接管更早的实验历史，可先做一次 lineage 回填：

```bash
python -m agent.training.lineage_backfill --apply
python scripts/update_research_workbench.py
```

该工具只自动补可确定事实；旧评测与模型版本之间的歧义关联仍要求通过 `research_workbench/lineage_overrides.json` 显式声明。

### 评价指标层

`agent/evaluation/` 是独立评价层，所有链路复用统一的 `MetricReport` 结构：`overall_score`、`grade`、`summary` 和按名称展开的 `metrics`。目前覆盖：

- `crawler.repo_profile` / `crawler.run`：架构覆盖、包文件、入口、测试、文档、CI、许可证、热度、导出率。
- `rag.unified_retrieval`：总命中、本地命中、学习库命中、学习库健康、来源多样性、耗时、截断率。
- `research.synthesis`：方案库命中、RAG 命中、Web 补充、`[S]/[R]/[W]` 引用覆盖、本地优先、LLM 综合状态。
- `training.dataset_prepare`：样本量、引用率、任务多样性、平均输出长度、拒绝率、切分质量、格式合法性。
- `training.dataset_governance`：密钥扫描、引用要求、重复率和人工复核门禁。

研究分链还会输出 `trace.evidence_policy`，按“方案库 > 本地/RAG > Web”的顺序做证据仲裁；Web 只作为补充，来源冲突会进入 `conflicts`，不静默覆盖本地证据。

### Model Plane / 本地大模型

本地大模型在项目里属于 **Model Plane**，与主链解耦：

```text
Agent Brain / Planner
  -> agent.llm.providers
  -> agent.llm.runtime
  -> agent.scheduler.routing
  -> OpenAI-compatible endpoint
  -> vLLM / SGLang / Transformers dev fallback / llama.cpp edge fallback
```

资源中心会把 `main_deepseek` 暴露为 `model_runtime` 资源，也会暴露 `model_pool` 资源；`model_runtime_status` action 可做只读状态检查：

```json
{"type":"action","action":"model_runtime_status","args":{"provider":"main_deepseek","probe":true,"timeout":2}}
```

`model_route_plan` 用于上线前的模型池准入和抢占规避：

```json
{"type":"action","action":"model_route_plan","args":{"goal":"长上下文RAG + 结构化Agent调用","prompt":"可选上下文","require_json":true,"max_output_tokens":1800}}
```

高并发上线链路应先 acquire lease：

```json
{"type":"action","action":"model_admission_acquire","args":{"goal":"短API请求","max_output_tokens":256,"idempotency_key":"req-001","lease_ttl_s":20}}
```

UI 也提供只读 API：

```bash
curl "http://127.0.0.1:7860/api/model-runtime?probe=0"
curl -X POST "http://127.0.0.1:7860/api/model-route-plan" -H "Content-Type: application/json" -d "{\"goal\":\"100+终端企业AI平台长上下文RAG请求\",\"max_output_tokens\":2048}"
curl -X POST "http://127.0.0.1:7860/api/model-admission/acquire" -H "Content-Type: application/json" -d "{\"goal\":\"短API请求\",\"max_output_tokens\":256}"
```

DeepSeek 本地部署脚本已提供在 `scripts/deploy_deepseek.py` / `scripts/deploy_deepseek_light.py`。是否“已部署运行”以健康检查或 `model_runtime_status` 为准：

```bash
curl http://127.0.0.1:8000/health
```

若未启动，可显式启动：

```bash
python scripts/deploy_deepseek.py --model deepseek-ai/DeepSeek-V2.5 --host 127.0.0.1 --port 8000
python -m agent.main --llm --provider main_deepseek --goal "创建一个简单的 Flask API" --workspace ./workspace_demo
```

在 6GB 显存或 Windows/vLLM 不可用环境，可使用轻量 Transformers 服务：

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
python scripts/serve_deepseek_transformers.py --model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B --host 127.0.0.1 --port 8000
```

方案库 + Web + LLM 综合：

```bash
python -m agent.main --llm --goal "先用 research_synthesize 查本地方案库和 Web，再设计员工审批管理系统" --workspace ./workspace_demo
```

Action 示例：

```json
{"type":"action","action":"research_synthesize","args":{"query":"员工审批管理系统 Spring Vue CRUD","top_k":4,"solution_dirs":["./product_runs"],"learning_dirs":["./learning_runs/demo"],"use_web":true,"use_llm":true,"llm_provider":"deepseek"}}
```

### CLI 补充

```bash
python -m agent.ui.app --host 127.0.0.1 --port 7860
python -m agent.learning.cli --query "Flask agent RAG" --local-repo ./workspace_demo --output ./learning_runs/demo
python -m agent.main --llm --provider groq --model openai/gpt-oss-20b --goal "写一个最小 Flask 接口 /hello 返回 ok"
python -m agent.main --demo --resume --resume-clear-errors --workspace ./ws
python -m agent.main --demo --events --policy ./my-policy.json
python -m agent.main --inspect-events ./workspace_demo/.agent_events.jsonl
python -m agent.main --inspect-events ./workspace_demo/.agent_events.jsonl --inspect-format json
python -m agent.main --inspect-events ./workspace_demo/.agent_events.jsonl --inspect-format markdown
python -m agent.main --inspect-events ./run-current/.agent_events.jsonl --inspect-baseline ./run-prev/.agent_events.jsonl
python -m agent.main --inspect-events ./run-current/.agent_events.jsonl --inspect-baseline ./run-prev/.agent_events.jsonl --inspect-format markdown
python -m agent.main --inspect-events ./run-current/.agent_events.jsonl --inspect-save ./reports/run-current.txt
python -m agent.main --inspect-events ./run-current/.agent_events.jsonl --inspect-baseline ./run-prev/.agent_events.jsonl --inspect-fail-on worsened
python -m agent.main --inspect-events ./run-current/.agent_events.jsonl --inspect-output-json ./reports/gate-result.json --inspect-fail-on critical
python -m agent.main --inspect-events ./run-current/.agent_events.jsonl --inspect-history ./reports/gate-history.jsonl --inspect-label nightly-main
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl --inspect-format markdown
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl --inspect-history-fail-on regression
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl --inspect-history-fail-on passrate --history-min-pass-rate 85 --inspect-output-json ./reports/history-gate.json
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl --inspect-history-fail-on duration --history-max-avg-duration 120 --inspect-output-json ./reports/history-duration-gate.json
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl --inspect-history-fail-on max_duration --history-max-duration 300 --inspect-output-json ./reports/history-max-duration-gate.json
python -m agent.main --inspect-history-report ./reports/gate-history.jsonl --history-label main --history-last 20
```

`--events` 写入的 JSONL 事件会包含稳定基础字段 `ts/kind/schema_version/event_id/run_id`，便于外部工具去重、引用、按单次运行聚合和回放。
`--inspect-events` 报告会包含：事件计数、运行耗时（`duration_seconds`）、运行聚合（`run_count/run_ids`）、策略/reward 汇总（strategy、policy selected action、alignment、avg reward）、阶段路径、RAG 召回路径 TopN、终态原因、告警分级（severity）、根因推断（root_cause）、下一步命令模板（next_command_templates）。
同时包含 planner 上下文利用指标：`context_hint_plan_hits`（包含 context 任务提示的 plan 次数）与 `context_hint_task_count`（提示任务总数）。
当提供 `--inspect-baseline` 时，会输出对比报告：severity 趋势、运行耗时 delta、终态变化、事件类型增减和阶段路径差异。
对比报告也会包含 `stage_context_delta` 与 `rag_path_delta/rag_truncated_delta`，用于查看各阶段 context 命中和 RAG 召回覆盖是提升还是退化。
报告还包含失败动作 TopN 与最近失败时间线；`--inspect-format markdown` 可直接贴到 PR/Issue。
`--inspect-save` 可将报告落盘，并自动生成 sidecar 元数据文件 `<report>.meta.json`（含 `analysis_id`、输入文件路径与 SHA256）。
`--inspect-fail-on critical|worsened|no_context_usage|stage_context_missing` 可用于 CI 闸门（命中时返回退出码 3）；`worsened` 会拦截 severity 变差，也会拦截 context/RAG 覆盖退化。
`no_context_usage` 用于拦截“存在 plan 但完全未命中 context 任务提示”的退化。
`stage_context_missing` 用于分阶段治理：目标阶段（默认 `coding,fixing,investigate`，可用 `--inspect-context-stages` 覆盖）只要有 plan 但无 context 命中就失败。
当 `--inspect-output-json` 与 `stage_context_missing` 联用时，gate JSON 会包含 `missing_context_stages` 方便 CI 直接定位。
`--inspect-output-json` 会输出稳定 gate 结果 JSON（`schema_version/analysis_id/status/severity/reason/final_progress/failure_reasons`）；若提供 baseline，还会包含 `severity_trend/worsened_reasons/stage_context_delta/rag_path_delta/rag_truncated_delta`，便于流水线直接消费。
`--inspect-history` 会将 gate 结果追加到历史 JSONL（包含 `failure_reasons/duration_seconds`）；可用 `--inspect-label` 打标签（如 `pr-123`、`nightly-main`、`staging`）。
`--inspect-history-report` 会输出历史趋势报告（通过率、平均/最大耗时、当前状态 streak、最近运行 TopN、最慢运行 TopN、failure reason 分布、severity 分布、标签分布、最近退化点）。
`--inspect-history-fail-on regression|passrate|duration|max_duration` 可对历史趋势设置闸门；`passrate` 使用 `--history-min-pass-rate` 作为阈值（默认 80），`duration` 使用 `--history-max-avg-duration` 作为平均耗时上限，`max_duration` 使用 `--history-max-duration` 作为单次最大耗时上限，命中时返回退出码 4；history gate JSON 会包含 `failure_reasons/current_status_streak/latest_runs/slowest_runs` 方便 CI 直接定位。
`--history-label` 可仅分析某个标签（如 `main`）；`--history-last` 可只看最近 N 条记录，适合短窗口治理。

### 测试

```bash
python -m pytest tests -q
```

## Action 协议

所有执行器输入为单行 JSON，字段见 `AIread.md` 第 59–75 行；`executor.py` 为唯一调度点。

## 疑问与更新

与 `AIread.md` 冲突之处以 **`AIread.md` 为准**；需扩展协议或阶段枚举时，请由你更新 `AIread.md` 后同步改本仓库对应模块。
