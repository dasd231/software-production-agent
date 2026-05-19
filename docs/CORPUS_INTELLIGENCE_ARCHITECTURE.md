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

当前已经补上第一层反馈控制面：

- `corpus_feedback_report.v1` 不只给建议，还会产出 `corpus_strategy.v1`；
- strategy 会把 `train_now_rate`、语料形状分布、`Recall@5` / citation precision 回归等信号转成下一轮可执行策略；
- 下一轮 query plan 会读取 facet promotion / suppression 与 query-arm 调整；
- crawler 本身会把 query plan 作为真实执行输入，并用 `max_query_arms` 限制网络查询上限；
- 下一轮 ranking 会读取权重覆盖、标签 utility 与更严格的 routing threshold。

它现在还是**透明控制器**，不是黑盒学习器。后续有了足够历史后，再把 query arm 升级成按回报更新的 bandit / contextual bandit。

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

如果上一轮反馈表明检索质量或引用精度下降，strategy 会显式提高 `docs/tests/entrypoints/package_manifest` 这类证据标签的 utility，重新归一化排序权重，并在必要时抬高下一轮最小质量门槛。这样“论文里解释得通”和“程序里真的会执行”是一回事。

## 4.1 项目化桥接

推荐层之后，系统不能只停在“这仓库值得看”。第一版桥接规则是：

| Route | 下游用途 |
| --- | --- |
| `train_now` | supervised training 候选 |
| `distill_pool` | 教师蒸馏候选 |
| `benchmark_holdout` | 只做 holdout，不可回流训练 |

`github_corpus_projectize` 会把这些仓库先转成 `repo_memory_v1`，再按 route 分桶合成 task assets。若同一仓库同时满足多个 route，`benchmark_holdout` 优先级最高，先把评测集隔离出来，避免训练泄漏。

`project_holdout_benchmark_build` 会只读取 `benchmark_holdout` 桶，生成项目级离线 benchmark；`project_holdout_evaluate` 接收预测结果后，直接输出：

- `recall_at_5`
- `mrr`
- `citation_precision`
- `answer_f1`
- `tokens_per_correct_answer`

如果提供 baseline report，还会生成 `feedback_deltas`，可直接回流给 corpus feedback。这样“语料推荐层”和“模型是否真的变强”开始形成同一条闭环。

训练入口则由 `github_corpus_training_bundle` 收口：它只把 `train_now` / `distill_pool` route 的 task assets 放入 `learning_dirs`，并把 `benchmark_holdout` 写入 holdout 清单但不交给 `training_prepare`。这让第一轮训练和论文评测的边界可以在 manifest 里直接审计。

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

第一版运行形态刻意没有做成“永不退出的巨型 daemon”，而是：

```text
systemd timer / cron
  -> github_corpus_flywheel_cycle
  -> one bounded crawl cycle
  -> projectization + holdout benchmark
  -> scheduler_state.json + corpus_strategy.json + flywheel_cycle_report.json
  -> process exits
```

这样有三个好处：

1. 每轮 `repo_limit`、`max_query_arms`、`cpu_thread_budget` 都是显式预算；
2. 上一轮 strategy 会通过 `scheduler_state.json` 自动传给下一轮；
3. 进程天然可停、可续、可审计，比共享服务器上的常驻死循环更稳。

`github_corpus_flywheel_cycle` 是推荐入口：它在一个 CPU-only 周期里串起 `scheduler cycle -> projectization -> holdout benchmark`。如果传入上一轮 `project_holdout_evaluation_report.json`，它会读取其中的 `feedback_deltas`，本轮 crawler feedback 就会据此调整 strategy。

CLI 入口是 `python -m agent.corpus_intelligence.cli flywheel ...` 和 `python -m agent.corpus_intelligence.cli training-bundle ...`。它们只是 action 的薄封装，便于 Linux 定时任务调用，不绕过协议中的资源预算与 holdout 隔离策略。

## 8. 本轮落地

这轮新增：

1. `github_corpus_program.v1`：把整套系统边界固定下来；
2. `github_query_plan.v1`：把 WebSearch 辅助发现变成显式对象；
3. `github_repo_ranking.v1`：把推荐与分流做成可解释对象；
4. `corpus_feedback_report.v1`：把模型反馈回流到语料层；
5. `corpus_strategy.v1`：把反馈变成下一轮 query / ranking / routing 可直接消费的策略；
6. crawler 侧写入 `query_plan.json`、`routing_report.json`、`feedback_report.json` 与 `corpus_strategy.json`；
7. `github_corpus_scheduler_plan/cycle` 提供单轮有界调度、状态续跑和 Linux timer 友好的运行形态；
8. `github_corpus_projectization_plan/projectize` 把 route 结果继续变成 repo-memory 与 route-separated project tasks；
9. `project_holdout_benchmark_build/evaluate` 把 holdout 资产变成可回流的项目级评价指标；
10. `github_corpus_flywheel_cycle` 把 scheduler、projectization、holdout benchmark 与上一轮 feedback delta 串成单轮可审计闭环。
11. `github_corpus_training_bundle` 把可训练 route 变成第一轮训练数据包，同时继续隔离 holdout。

这意味着 GitHub 不再只是“数据来源”，而是正式成为训练系统的第一层智能入口。
