# 备用本地模型训练链路

本项目把“可以训练”拆成两件事：**数据已经足够可信**，以及 **当前环境真的具备训练条件**。这样做的目的不是把训练入口做得更复杂，而是避免知识库质量、样本污染、依赖缺失和显存不可用被隐藏到训练开始之后才暴露。

## 1. 设计目标

备用本地模型不是主模型的随意复制品，而是基于高质量知识资产训练出的候选版本。它承担两类职责：

- 当主模型不可用时，提供受控的本地后备能力；
- 作为可审计的实验分支，承接知识库和方案库沉淀出的增量能力。

因此，训练链路必须同时满足三类约束：

| 约束 | 含义 |
| --- | --- |
| 数据可信 | 训练样本来自已晋级知识资产，并经过二次样本审查 |
| 过程可审计 | 每次训练任务都有 spec、环境探测、门禁结果、版本清单和 manifest |
| 上线可治理 | 训练成功不等于可替换主模型，rollout 前仍需要人工评估和灰度验证 |

## 2. 链路结构

```text
learning run
  -> slice/card/knowledge quality review
  -> promoted knowledge only
  -> training_prepare
       -> sample_quality_report.json
       -> protocol_examples.jsonl
       -> dataset_snapshot_manifest.json
       -> governance_report.json
       -> train.jsonl / eval.jsonl
  -> backup_model_train
       -> data_gate.json
       -> training_environment.json
       -> resource_preflight.json        # 开训时由 safe launcher 生成
       -> backup_training_spec.json
       -> training_job_spec.json
       -> training_job_manifest.json
       -> model_version_manifest.json
       -> launch_command.txt
```

这条链路强调“先审、再训”：

1. `learning` 阶段先对切片、知识卡和仓库级知识资产做门禁；
2. `training_prepare` 只消费已晋级资产，并再次对训练样本做样本级复审；同时默认注入一组可审计的 `action_protocol_sft` 样本，专门训练模型输出严格 action JSON；
3. `backup_model_train` 在真正进入训练前，再检查样本数量、质量分、治理状态、依赖、CUDA 和基座模型配置。

## 3. 质量门禁

`backup_model_train` 当前使用以下阻塞条件：

| 门禁 | 阻塞码 |
| --- | --- |
| 训练样本数量不足 | `insufficient_train_examples` |
| 样本质量分低于阈值 | `sample_quality_below_threshold` |
| 治理扫描阻塞 | `dataset_governance_blocked` |
| 缺少 `train.jsonl` | `missing_train_jsonl` |
| 训练依赖不完整或 CUDA 不可用 | `blocked_environment` |
| 未提供基座模型 | `blocked_missing_base_model` |

当上述条件全部通过后，系统才会把任务标记为 `launch_ready` 或 `prepared_not_started`。

数据准备阶段还会记录 `min_task_share`，用来暴露“任务种类虽然齐全，但某个能力切片几乎消失”的情况。  
例如只有 1 条 `rag_grounded_answer` 时，`task_diversity` 仍可能很好看，但 `min_task_share` 会把这种极端失衡标成 `watch`。
研究工作台会优先读取正式指标；如果是更早生成、尚未写入该字段的历史 run，则会依据已冻结的数据快照任务配比派生同口径结果，便于横向比较。

## 4. 主要产物

| 文件 | 作用 |
| --- | --- |
| `backup_training_spec.json` | 训练配置、数据路径、超参数和输出位置 |
| `training_job_spec.json` | 与执行后端解耦的标准训练任务定义 |
| `training_job_manifest.json` | `created -> validated -> queued -> ...` 的训练作业生命周期 |
| `training_environment.json` | 依赖包、PyTorch、CUDA 与设备探测 |
| `data_gate.json` | 数据质量与治理门禁结果 |
| `model_version_manifest.json` | 候选模型版本、基座、适配器、质量摘要 |
| `launch_command.txt` | 规范化启动命令 |
| `resource_preflight.json` | 共享服务器资源门禁；记录 GPU 空闲状态和是否允许开训 |
| `report.md` | 人工审查友好的摘要 |
| `run_manifest.json` | 可追踪输入、产物、来源和风险 |
| `protocol_examples.jsonl` | 协议跟随专项样本，来自可执行 schema，而非普通知识库 |
| `dataset_snapshot_manifest.json` | 冻结后的训练数据快照、来源、任务配比、内容 hash 与 shard manifest |

## 5. 使用方式

Windows / RTX 本地训练环境建议先用独立虚拟环境准备：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_training_env.ps1
```

脚本会创建 `.venv-train`，安装 CUDA 版 PyTorch 与 `requirements-training.txt` 中的训练栈，并在结束时打印训练环境探测结果。

先准备训练集：

```json
{"type":"action","action":"training_prepare","args":{"output_dir":"./training_runs/demo","learning_dirs":["./learning_runs/demo"],"solution_dirs":["./product_runs"],"dataset_format":"messages","eval_ratio":0.15,"include_protocol_examples":true}}
```

再生成备用模型训练任务：

```json
{"type":"action","action":"backup_model_train","args":{"training_dir":"./training_runs/demo","output_dir":"./model_runs/backup-demo","base_model":"deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B","adapter_name":"backup-local-lora","launch":false}}
```

## 6. 当前边界

- 本链路现在已经把训练前的质量、治理、环境和版本管理打通；
- 当前默认把动作协议样本纳入训练集，避免模型只会“解释知识”而不会“执行动作”；
- 训练任务已经从单脚本入口升级为标准 job，可在未来由 Linux 远程 runner 或集群 runner 接管执行；
- `agent.training.backup_trainer` 是真实 LoRA/SFT 训练入口，但仍然需要显式执行；
- 真正上线前还需要补充模型评测、对照基线、人工验收和灰度策略，不能只凭“训练完成”就替换主模型。

训练入口现在默认通过 `safe_launcher` 进入。它会先检查共享服务器资源，再决定是否允许进入真正训练。  
训练入口支持先做一次干跑：

```bash
.\.venv-train\Scripts\python.exe -m agent.training.safe_launcher --config ./model_runs/backup-demo/backup_training_spec.json --dry-run
```

如果环境与数据都通过，再显式启动：

```bash
.\.venv-train\Scripts\python.exe -m agent.training.safe_launcher --config ./model_runs/backup-demo/backup_training_spec.json
```

完成训练后，进行模型评测时建议把模型版本清单一并传入：

```bash
.\.venv-train\Scripts\python.exe -m agent.training.backup_eval `
  --benchmark ./benchmarks/backup_model_eval.v3.json `
  --base-model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B `
  --adapter-dir ./model_runs/backup-demo/adapter `
  --output-dir ./model_evals/backup-demo-benchv3 `
  --label backup_demo_benchv3 `
  --model-version-manifest ./model_runs/backup-demo/model_version_manifest.json
```

这样生成的 `model_evaluation_report.json` 会带上 `subject.model_version` 等字段，研究工作台即可把“数据快照 → 训练作业 → 模型版本 → 评测结果”精确串起来，而不是只做名称猜测。

如果需要继续判断候选模型是否值得进入人工评审，再执行一次晋级门禁：

```bash
.\.venv-train\Scripts\python.exe -m agent.training.promotion `
  --baseline-report ./model_evals/backup-demo-base-benchv3/model_evaluation_report.json `
  --candidate-report ./model_evals/backup-demo-tuned-benchv3/model_evaluation_report.json `
  --model-version-manifest ./model_runs/backup-demo/model_version_manifest.json `
  --output-dir ./model_evals/backup-demo-tuned-benchv3
```

门禁会输出 `model_promotion_decision.json` 与 `promotion_report.md`。  
`ready_for_manual_review` 表示“值得继续人工评审”，不表示“已经可以自动替换主模型”。
