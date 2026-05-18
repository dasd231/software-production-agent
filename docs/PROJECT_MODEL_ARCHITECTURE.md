# 项目大模型架构

本项目的新北极星不再只是训练一个“会调用动作协议”的备用 Agent，而是训练一个真正擅长**理解软件项目**的模型：

> 在有限 token、有限延迟和真实工程约束下，尽可能高效地读懂一个仓库。

这里的“项目”不是单个源码片段，而是一个由下列要素共同构成的对象：

- 源码与目录结构；
- README、设计文档、ADR；
- 依赖清单、构建配置；
- 测试、CI、示例；
- issue、PR、commit、release note 等演化轨迹。

## 1. 方向判断

如果目标是项目级理解，那么只做两件事都不够：

1. 只继续堆代码 token；
2. 只把更多文件塞进更长上下文。

真正需要训练的是：

- **项目表示**：模块、符号、依赖、边界；
- **证据检索**：先找到最少但足够的文件和 span；
- **跨文件推理**：解释调用链、影响面和实现位置；
- **项目记忆**：把仓库压缩成可复用、可更新的结构化表示；
- **演化理解**：把 issue/PR/commit 与代码变化对应起来。

## 2. 总体形态

```text
Internet-scale Project Corpus
├── repository snapshots
├── docs / ADR / README
├── manifests / dependency graph
├── tests / CI / examples
└── issues / PRs / commits / releases

        ↓ provenance + license + dedup

Project Representation Layer
├── repo structure map
├── symbol index
├── dependency graph
├── project memory card
└── evidence index

        ↓

Retriever + Reader Training
├── evidence retrieval
├── repo-grounded QA
├── issue-to-code localization
└── architecture summarization

        ↓

Engineering Reasoning Alignment
├── change impact reasoning
├── test-guided fixing
└── cross-file completion
```

## 3. 数据原则

“极致网络训练”不等于“无差别抓全网”。  
真正可持续的定义应是：

> 在治理边界内，尽可能扩大开放网络覆盖，并且保留每条样本的来源、许可证、版本与证据位置。

仓库中已经新增 `agent/project_model/`，把第一版数据源分为六类：

| Source | 作用 |
| --- | --- |
| `open_repo_snapshots` | 代码与目录树基础语料 |
| `repository_docs` | 架构语义 |
| `dependency_manifests` | 依赖与构建关系 |
| `development_traces` | 需求、讨论与演化 |
| `official_reference_docs` | 外部库语义 |
| `execution_signals` | 行为与测试 |

这六类数据共同组成“项目对象”，避免模型只学会局部代码补全。

## 4. 训练阶段

### Stage 0：Corpus foundation

先解决数据治理，不急着开训：

- 许可证；
- 来源；
- 去重；
- repo / commit / path / span 统一标识；
- 代码、文档、测试、依赖和演化数据的链接关系。

### Stage 1：Repository representation pretraining

先让模型学会仓库是什么：

- 目录结构；
- 模块边界；
- 符号定位；
- 依赖关系；
- 跨文件补全；
- 架构摘要。

### Stage 2：Retrieval-grounded understanding

这是第一条真正值得投入的主线：

- 给问题；
- 先找证据；
- 再回答；
- 强制回答附带引用；
- 衡量 token 效率，而不是只看能否最终答出来。

### Stage 3：Engineering reasoning alignment

当模型已经会“读懂”，再训练它“理解工程变化”：

- issue 到代码定位；
- 改动影响面；
- 测试关联；
- 修复计划；
- 跨文件完成。

## 5. 为什么当前先做 Retriever + Reader

它比“直接从零预训练项目大模型”更贴近你现在的条件：

- 能在单机 GPU 上先做小规模实验；
- 更容易形成可测指标；
- 对未来大规模继续预训练也不浪费；
- 最能直接改善“读项目慢、读不准、上下文浪费大”这个核心问题。

所以当前推荐的第一建设目标不是一个空泛的“基础模型”，而是：

```text
repo_memory_v1
├── project map
├── symbol index
├── evidence index
├── grounded QA samples
└── holdout evaluation report
```

## 6. 评测口径

项目大模型不能只看 loss。至少要同时看：

| 维度 | 指标 |
| --- | --- |
| 证据检索 | Recall@5、MRR |
| 符号定位 | symbol recall、definition exact match |
| 跨文件推理 | edge F1、path recall |
| 仓库问答 | answer F1、citation precision |
| 架构理解 | coverage、faithfulness |
| 工程推理 | impact F1、test recall |
| 效率 | tokens per correct answer、latency |

仓库中的 `project_model_program.v1` 已经把这些能力切片映射到公开基准和内部 holdout 评测。

## 7. 与现有系统的关系

现有训练控制面仍然保留，而且更有价值：

- `dataset_snapshot_manifest.json` 继续做数据事实源；
- `training_job_spec.json` 继续描述训练任务；
- `promotion` 继续做模型晋级门禁；
- `agent/distributed/` 继续承接未来的 Ray / Spark / Flink 演进。

变化的是**上游语料与任务本体**：

- 过去训练的是 Agent 的局部技能；
- 现在要训练的是模型对“整个软件项目”的表征、检索和推理能力。

## 8. 本轮落地

本轮代码先做四件事：

1. 新增 `agent/project_model/`，固定项目大模型的数据源、任务、阶段和基准目录；
2. 新增 `project_model_program_plan` action，让控制面能直接读取这套路线；
3. 新增 `project_repo_memory_build`，把单仓库压成 `project_map`、`symbol_index`、`evidence_index` 与 manifest；
4. 新增 `project_task_synthesis_build`，把 repo-memory 转成第一批项目级 SFT 样本和 retrieval pairs；
5. 把仓库级语料加工加入分布式 workload catalog；
6. 把项目大模型路线写入 research workbench，后续可以继续往 retriever 训练和 benchmark runner 推进；
7. GitHub corpus 侧新增 `github_corpus_projectize`，把 crawl route 直接接到 repo-memory / task synthesis，并把 `benchmark_holdout` 从训练资产中隔离。

这意味着“项目大模型”不再只是战略描述，而是已经进入当前仓库的正式能力边界。
