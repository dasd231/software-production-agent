# GitHub 语料智能层

这一层解决的不是“怎么再爬一个仓库”，而是：

> 怎样把 GitHub 长期变成一条可控、可解释、可反馈的项目语料生产线。

它位于现有训练系统的最上游。

```text
GitHub / WebSearch
  -> Discovery
  -> Recommendation & Routing
  -> Project Object Builder
  -> Distillation / Student Training
  -> Evaluation
  -> Feedback back to Discovery
```

## 1. 模块边界

| 模块 | 负责什么 |
| --- | --- |
| Discovery | 查询种子、WebSearch 扩词、持续抓取调度 |
| Recommendation & Routing | 对候选仓库打分，并分流到训练、蒸馏、benchmark 或隔离区 |
| Project Object Builder | 把仓库转成 `project_map`、`symbol_index`、`evidence_index`、任务样本 |
| Distillation | 让外部教师模型教会学生模型更强的项目理解 |
| Student Training | 基于 DeepSeek 开源基座做 LoRA/QLoRA 微调 |
| Evaluation & Feedback | 把候选质量、训练集质量、模型收益重新回流到发现层 |
| Ops Guard | 让 Linux 常驻程序 CPU 优先，GPU 任务受共享服务器门禁约束 |

## 2. 搜索算法

第一版采用：

```text
operator seed queries
  + WebSearch title/snippet facets
  -> 去重
  -> MMR 风格的词面多样性选择
  -> GitHub query plan
```

原因很简单：

- 只靠固定 query，会越来越窄；
- 只靠 WebSearch，又容易漂；
- 先把“种子查询”和“网页启发词”混合，再做多样性控制，能同时保住 exploitation 与 exploration。

后续有了足够历史后，再把 query arm 升级成按回报更新的 bandit / contextual bandit。

## 3. 推荐与分流算法

当前 v1 使用透明的多目标打分：

| 维度 | 含义 |
| --- | --- |
| lexical relevance | 与目标能力是否相关 |
| repo quality | 结构、测试、文档、CI、许可证等 |
| freshness | 是否仍然活跃 |
| governance | 许可证与治理是否可接受 |
| novelty | 是否补充了当前语料缺失的项目形状 |
| downstream utility | 过去这种项目是否真的提升了模型 |

它不是只给一个总分，而是同时输出：

- `train_now`
- `distill_pool`
- `benchmark_holdout`
- `observe`
- `quarantine`

这就是系统里的“信息分流和推荐”层。

## 4. 为什么要接 WebSearch

GitHub Search 更像结构化检索；WebSearch 更像外部世界对“什么值得看”的提示。  
两者结合后：

- WebSearch 负责提供新词、新框架、新方向；
- GitHub Search 负责真正落到可抓取仓库；
- 推荐层负责判断这些仓库值不值得进训练链。

## 5. 模型路线

自研学生模型路线固定为：

1. 以 **DeepSeek 开源模型家族**为底座；
2. 先做 adapter-first 微调；
3. 第一轮先用轻量可复盘基座；
4. 后面再逐步扩展到更强 coder lane；
5. 外部强模型只通过 distillation 变成训练资产，不替代自有学生模型主线。

当前代码里已经把首轮学生模型默认落在：

- `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B`

并保留 coder lane：

- `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct`

## 6. 评价指标

评价必须分层，否则很容易“爬得多但学得差”。

| 层级 | 指标 |
| --- | --- |
| Discovery | query yield、accepted candidate rate、novelty rate、license pass rate、dedupe rate |
| Repo Quality | repo quality score、architecture coverage、docs/tests/CI present rate |
| Dataset | grounded required rate、citation rate、duplicate rate、task diversity、min task share |
| Model | Recall@5、MRR、citation precision、answer F1、faithfulness、impact F1、tokens per correct answer |
| Ops | crawl backlog、queue latency、GPU admission pass rate、foreign GPU process block rate、job failure rate |

## 7. 常驻 Linux 程序形态

常驻程序不是一个“疯狂抢资源的大进程”，而是几类角色拆开：

- crawler scheduler；
- CPU repo profiler workers；
- project-object builders；
- dataset / eval workers；
- 只有通过共享服务器门禁后才允许启动的 GPU training worker。

这让系统可以一直跑，但不会因为“持续爬取”就持续占 GPU。

## 8. 本轮落地

这轮新增：

1. `github_corpus_program.v1`：把整套系统边界固定下来；
2. `github_query_plan.v1`：把 WebSearch 辅助发现变成显式对象；
3. `github_repo_ranking.v1`：把推荐与分流做成可解释对象；
4. `corpus_feedback_report.v1`：把模型反馈回流到语料层；
5. crawler 侧开始写入路由结果，后续可以继续接常驻调度器。

这意味着 GitHub 不再只是“数据来源”，而是正式成为训练系统的第一层智能入口。
