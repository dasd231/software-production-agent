# Intent AgentOS Vision

> 目标：不是复刻蓝图开发或 Coze Studio 式低代码画布，而是做一个“意图到生产”的软件生产操作系统。

## 核心判断

Coze Studio、Dify、AutoGen Studio 这类平台的强点，是把 Prompt、RAG、Plugin、Workflow、Knowledge Base、调试和发布放进一个统一资源面板。我们要吸收的是这个“资源统一 + 工作流可视化 + 组件复用”的思想；但如果只做一个画布，会很快陷入节点堆叠、调试困难、可追溯弱、工程交付弱的问题。

本项目应该走另一条路：

1. 用户先说意图，不先拖节点。
2. 系统把意图编译成 `workflow.v1`。
3. workflow 先校验、dry-run、解释风险，再执行。
4. 每次执行都写 manifest、evaluation、governance 和 evidence ledger。
5. 成功 run 自动变成 solution asset，进入 RAG 和训练数据筛选。
6. 未来再做画布，但画布只是 workflow 的可视化编辑器，不是系统核心。

这就是“主链 + 分链”的成熟版：主链负责意图、治理、调度和资产闭环；分链负责 research、crawler、training、solution publish、evidence ledger 等可替换能力。

## 已落地能力

### Intent Compiler

入口：`intent_compile`

位置：`agent/intent/compiler.py`

作用：

- 从自然语言目标提取意图标签，例如 `crawler`、`training`、`frontend-backend`、`asset-publish`、`evidence`。
- 生成轻量 `workflow.v1`。
- 调用 `workflow_validate` 和 `workflow_dry_run`。
- 给出本地资源建议与风险提示。

这一步是替代低代码的关键：用户不需要先理解节点系统，系统先给出可解释的执行草案。

### Workflow Dry Run

入口：`workflow_dry_run`

位置：`agent/workflows/dry_run.py`

作用：

- 展示执行顺序。
- 展示每个节点 action、权限、成本、联网/写文件风险。
- 展示预期产物。
- 给出前置门禁，例如 protocol validation、workspace path guard、evidence capture、evaluation report。

这让 workflow 在执行前可审查，避免低代码画布常见的“能连起来但不知道会发生什么”。

### Evidence Ledger

入口：`evidence_ledger`

位置：`agent/evidence/ledger.py`

作用：

- 汇总 `run_manifest.json`、`solution_manifest.json`、`evaluation_report.json`、`governance_report.json` 和 `.agent_events.jsonl`。
- 输出 `evidence_ledger.v1`。
- 被 `resource_registry` 发现为 `evidence_ledger` 资源。

这是项目的护城河之一：Agent 产出不只是代码，还能留下证据、评分、风险、来源和可回放记录。

### Solution Publish

入口：`solution_publish`

位置：`agent/solution_library/publish.py`

作用：

- 只在用户显式验收满意后，把 run 发布为本地方案资产。
- 写入 `solution_manifest.v2`。
- 写入 `docs/SOLUTION_BACKUP.md`。
- 写入发布链路的 `run_manifest.json`。
- 推断技术栈和检索标签。

这让项目开始形成更干净的软件工厂飞轮：交付候选 -> 用户验收 -> 正式方案库 -> RAG -> 训练数据 -> 更强产物。

## 创新点

### 1. 意图编译，而不是画布优先

低代码平台一般从节点和画布开始。本项目应该从自然语言目标开始，用编译器生成 workflow，再允许人编辑。这样更适合复杂软件生产，因为用户真正关心的是“我要做什么”，不是“一开始应该拖哪几个节点”。

### 2. Workflow Contract First

所有分链必须先注册到 `agent/chains/registry.py`，暴露：

- action
- input/output schema
- permissions
- cost level
- timeout
- network/write flags
- evaluation stage

这让 UI、执行器、资源中心、dry-run、创新雷达都能共享同一份能力目录。

### 3. Evidence-Governed RAG

RAG 不只是召回文本。成熟版本应该让每次回答携带：

- local solution evidence
- learning/RAG evidence
- web evidence
- conflict notes
- evaluation score
- ledger entry

未来训练数据也应该只从 evidence ledger 中筛选，而不是直接从杂乱文本里抽样。

### 4. Software Factory Flywheel

每次项目生成都不应该结束在 ZIP 包。正确闭环是：

```text
Goal -> Intent Workflow -> Run -> Evaluation -> Solution Asset -> RAG -> Training Dataset -> Model/Policy Improvement
```

这个飞轮比“低代码搭应用”更有长期价值，因为它会越用越强。

### 5. 主链自治 + 分链可插拔

主链不应该塞满所有逻辑。成熟结构应该是：

- 主链：意图编译、资源选择、权限检查、执行编排、证据治理、回放。
- Research 分链：本地方案 + RAG + Web + LLM 综合。
- Crawler 分链：GitHub/本地项目画像、质量判断、标签、方案导出。
- Training 分链：SFT 数据、治理报告、训练计划。
- Publish 分链：方案资产发布。
- Ledger 分链：证据账本。

后续其它架构进来训练时，只要注册成新分链和新资源类型，不需要改主链大脑。

## 下一阶段路线

### 近期

1. 把 `/intent` 做成工作台：编译、dry-run、资源建议、风险、workflow JSON 一屏完成。
2. 把 `solution_publish` 接到 run 结果页按钮。
3. 把 `evidence_ledger` 接入结果页，展示证据覆盖率、评价分、治理风险。
4. 在 `training_prepare` 里优先读取 evidence ledger，筛掉低质量、低引用、治理风险高的样本。

### 中期

1. 做 workflow executor：从 `workflow.v1` 逐节点执行 action，而不是只校验。
2. 做 workflow template library：把高频流程沉淀为模板。
3. 做 visual canvas，但它只编辑 `workflow.v1`，不绕过协议和 dry-run。
4. 做 asset marketplace：方案、知识库、训练集、模型 provider、分链都能被搜索、评分、复用。

### 长期

1. 做自进化策略层：根据 run 成功率、测试结果、用户二次改进次数、方案复用率更新分链选择策略。
2. 做多模型路由：DeepSeek、本地模型、OpenAI、Groq 根据任务阶段自动调度。
3. 做组织级权限与审计：用户、项目、方案资产、训练数据都有 owner、role、approval 和 audit trail。
4. 做分布式执行：crawler、training、eval 可进入 worker queue，UI 用 SSE/WebSocket 展示状态。

## 不做什么

- 不把所有逻辑塞到一个巨型 Agent loop。
- 不让画布绕过 action protocol。
- 不直接把 GitHub 代码盲目塞进训练数据。
- 不把 Web Search 结果当最终事实，必须和本地方案、RAG、引用和评价合并。
- 不把训练当“攒 jsonl”，必须有治理、引用、质量和可回放 manifest。

## 参考

- Coze Studio GitHub：<https://github.com/coze-dev/coze-studio>
- Coze Studio Wiki：<https://github.com/coze-dev/coze-studio/wiki/1.-What-is-Coze-Studio>
- Coze Studio 中文 README：<https://github.com/coze-dev/coze-studio/blob/main/README.zh_CN.md>
