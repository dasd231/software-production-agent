# 训练架构设计

本项目将模型训练设计为由 **训练控制面（Training Control Plane）**、**训练执行面（Training Execution Plane）** 与 **训练数据面（Training Data Plane）** 共同组成的分层系统，而不是将训练逻辑直接绑定在某一台机器或某一个脚本中。

这样设计有三个直接目标：

1. 本地可以轻量完成训练层设计、数据配比调整、实验定义与质量治理；
2. 每一次训练都具备完整证据链，能够追溯到数据来源、任务配置、执行状态和最终产物；
3. Linux 服务器或后续集群只承担算力执行任务，避免业务规则与 GPU 环境强耦合。

## 1. 分层结构

```text
Training Control Plane
├── Training Studio
│   ├── training_recipe.v1
│   ├── training knob registry
│   └── ablation_plan.v1
│
├── Dataset Registry
│   ├── dataset_snapshot_manifest.json
│   ├── task mix
│   ├── quality reports
│   └── shard manifest
│
├── Experiment / Job Registry
│   ├── training_job_spec.json
│   ├── training_job_manifest.json
│   ├── model_version_manifest.json
│   └── run_manifest.json
│
├── Runner Abstraction
│   ├── local_trl
│   ├── linux_remote   (contract-ready)
│   ├── accelerate     (planned)
│   ├── torchrun       (planned)
│   └── deepspeed      (planned)
│
└── Evaluation Gate
    ├── benchmark binding
    ├── model_evaluation_report.json
    ├── model_promotion_decision.json
    └── promotion decision

Training Execution Plane
├── local workstation
├── Linux single-node GPU server
└── future multi-node cluster

Adjacent Enterprise Planes
├── Distributed Execution Plane
│   └── Ray-first contract layer for learning/eval/training-dispatch workloads
├── Batch Data Plane
│   └── Spark when dataset preparation outgrows local JSONL/Python workflows
└── Streaming Data Plane
    └── Flink only when stateful real-time flows become a real requirement
```

## 2. 数据面：从训练集到训练快照

`training_prepare` 完成后，系统会在训练目录中生成 `dataset_snapshot_manifest.json`。它记录：

| 字段 | 作用 |
| --- | --- |
| `dataset_id` | 冻结后的数据集唯一标识 |
| `source_manifest_id` / `source_refs` | 训练数据来源 |
| `counts` | dataset/train/eval 样本数 |
| `task_mix` | 各任务类型配比 |
| `quality` | 样本质量、治理和评价报告 |
| `files` | 关键文件路径与内容 hash |
| `sharding` | train/eval 分片及每片 hash |
| `storage_profile` | 当前 JSONL 事实源、未来 Parquet/对象存储迁移意图与 Spark 准备状态 |

这一设计使训练数据从“若干 JSONL 文件”升级为“可复制、可验证、可分发的数据快照”。后续远程 Linux 训练或集群训练不需要重新理解原始学习链，只需消费该快照及其 shard manifest。

## 3. 控制面：从训练配置到标准作业

在 `training_job_spec.json` 之上，系统现在显式区分两类更偏研究设计的对象：

| 对象 | 作用 |
| --- | --- |
| `training_recipe.v1` | 面向研究者，说明这次为什么训、怎么训、哪些旋钮可调 |
| `ablation_plan.v1` | 面向实验设计，说明各 variant 相对 baseline 改了什么、如何比较 |

这两类对象不替代 `training_job_spec.json`。  
前者回答“研究设计”，后者回答“执行契约”。这样可以避免把 teacher mix、task mix、实验假设和 runner 参数混在同一层里。

如果一轮实验使用蒸馏，控制面还会额外经过一组显式对象：

| 对象 | 作用 |
| --- | --- |
| `teacher_task_suite.v1` | 定义教师要教哪些能力 |
| `distillation_plan.v1` | 定义教师配比、学生模型和接收门槛 |
| `teacher_prompt_batch.v1` | 把源样本转成带证据的教师 prompt |
| `teacher_execution_plan.v1` | 在默认 `dry_run` 下预览教师调用 |
| `teacher_execution_result.v1` | 记录真实教师执行、失败请求和 token 用量 |
| `teacher_output_review.v1` | 依据 prompt 证据审查教师输出 |
| `distillation_export_manifest.v1` | 把通过审查的输出导回 `training_prepare` |

这让“蒸馏”保持为可检查的训练设计，而不是一段隐藏在脚本里的 API 调用。

为了让第一次训练不被一堆分散动作拖住，系统还提供 `first_training_round_plan.v1`。  
它不替代训练链，而是把第一轮最短路径固定成：

```text
review source learning dirs
  -> training_prepare
  -> inspect dataset snapshot / quality
  -> backup_model_train launch=false
  -> explicit server launch
```

这样首轮训练先追求“能复盘、能比较、能安全挂起来”，而不是一上来就追求最大语料或最大模型。

`backup_model_train` 当前仍保留兼容用的 `backup_training_spec.json`，同时新增两类通用产物：

| 文件 | 作用 |
| --- | --- |
| `training_job_spec.json` | 标准训练任务说明，描述训练目标、基座模型、数据快照、后端、资源、超参数、评测基准和产物契约 |
| `training_job_manifest.json` | 作业生命周期与执行状态清单 |

当前的 `training_job_spec.json` 还进一步显式包含：

| 字段 | 作用 |
| --- | --- |
| `execution_profile` | 描述训练运行位置、runner、资源形态和调度方式 |
| `sync_contract` | 描述远端执行前后必须同步的输入、输出与校验规则 |
| `resume_policy` | 描述断点恢复策略 |
| `retry_policy` | 描述可重试失败与重试上限 |

`training_job_manifest.json` 采用以下生命周期：

```text
created -> validated -> queued -> dispatched -> running -> completed -> evaluated -> promoted
```

该状态机使训练任务可以在本地先完成设计和审核，再被远程执行面接管；如果未来需要失败恢复、重试或多节点调度，也无需改变上层业务结构。

同时，`training_job_manifest.json` 还保留远端执行需要的运行字段，例如 `remote_job_id`、`execution_host`、`resume_from_checkpoint`、`last_heartbeat_at`、`failure_classification` 和 `retry_count`。这使作业既能被论文复盘，也能被实际调度系统接管。

## 4. 执行面：Runner 抽象

当前项目已提供：

```text
TrainingRunner
├── LocalTRLRunner
└── LinuxRemoteRunner
```

`LocalTRLRunner` 只是一种执行后端，不再代表训练架构本身；`LinuxRemoteRunner` 当前已经提供契约层定义，但尚未真正接入 SSH / 队列派发器。后续 Linux 服务器接入时，可以在不改变训练任务定义的前提下继续扩展：

| Runner | 目标 |
| --- | --- |
| `linux_remote` | 单台远程 Linux 主机训练 |
| `accelerate` | 单机多卡 |
| `torchrun` | 原生 PyTorch 分布式 |
| `deepspeed` | ZeRO、显存优化和大模型训练 |
| `ray_cluster` | Python 原生分布式任务 / 训练派发执行面 |
| `cluster_runner` | Slurm / Kubernetes / 队列系统 |

换言之，本地侧负责回答“训什么、为什么训、是否可信”，Linux 侧只负责回答“在哪里更快地训完”。

## 4.1 本地—远端同步契约

每个训练作业都可以携带 `training_sync_contract.v1`，明确：

- 哪些输入在 dispatch 前必须存在，例如 dataset manifest、train/eval 文件和 shard；
- 哪些输出在完成前必须回传，例如 adapter、training result、日志和 checkpoint；
- 是否校验输入 hash；
- 断点恢复时如何选择 checkpoint。

这样做的意义是把“把文件拷过去再训练”提升为“可验证的数据与产物传输协议”。服务器接入后，只需要实现这个契约，而不必重新理解你的研究设计逻辑。

## 5. 证据闭环

一次完整训练会形成以下证据链：

```text
learning run
  -> quality reports
  -> optional distillation prompt/review/export
  -> training_prepare
  -> dataset_snapshot_manifest.json
  -> backup_model_train
  -> training_job_spec.json
  -> training_job_manifest.json
  -> adapter / checkpoints / training_result.json
  -> model_evaluation_report.json
  -> model_promotion_decision.json
  -> model_version_manifest.json
```

资源中心已经能够识别：

- `dataset_snapshot`
- `training_job`
- `model_version`
- `model_evaluation`

因此系统可以回答：

- 这次训练用了哪一版数据；
- 这版数据由哪些来源生成；
- 每类样本占比是多少；
- 训练任务被投递到哪个后端；
- 训练是否真正完成；
- 最终模型是否通过评测门禁。

评测门禁当前以独立产物 `model_promotion_decision.json` 表达。它只回答“是否值得进入人工评审”，并不会越权把模型直接切到生产态；这让训练平台既具备自动化判断，又保留上线前的人类审批边界。

对于早期先于控制面产生的历史产物，`agent.training.lineage_backfill` 负责做兼容升级：重建缺失的 training job、回填 dataset/job 引用、通过 benchmark case 签名恢复 `benchmark_id`，并把需要人工确认的旧评测映射收敛到显式 override，而不是让系统按名称猜测。

## 6. 从本地到 Linux，再到集群

### 阶段一：本地训练设计

- 在本地完成知识质量控制；
- 生成 dataset snapshot；
- 定义 training job；
- 用 `local_trl` 做小规模验证。

### 阶段二：Linux 单机执行

- 远程同步 dataset snapshot / shards；
- Linux runner 读取同一份 `training_job_spec.json`；
- 通过 `accelerate`、`torchrun` 或 `deepspeed` 利用多卡；
- 回传日志、checkpoint、adapter 和 metrics。

### 阶段三：集群扩展

- 控制面根据资源需求选择执行后端；
- 训练 shard 由不同节点读取；
- job manifest 记录 dispatch / retry / resume；
- 产物统一回写模型注册表和评测门禁。

### 阶段四：数据平台扩展

- 当训练数据规模超出本地 JSONL/Python 准备链后，再把数据集构建迁移到 Spark / Parquet / 对象存储；
- 当审计流、在线监控或实时特征真正需要有状态流处理时，再引入 Flink；
- 这两者都属于数据面，不替代现有训练控制面。

## 7. 设计价值

该架构的核心不在于“用了哪一种微调库”，而在于将模型训练从脚本级能力提升为平台级能力：

- **本地可设计**：便于快速迭代训练层和任务结构；
- **全程可追溯**：支撑论文复现和工程审计；
- **执行可迁移**：服务器和集群只替换 runner，不推翻控制面；
- **规模可扩展**：通过快照、分片和作业状态机支撑更大规模训练。
