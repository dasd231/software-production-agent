# 第一轮训练

第一轮训练的目标不是直接得到最强模型，而是先把 **数据 → 训练集 → 训练任务 → 服务器执行** 这条链路完整跑通，并留下可复盘证据。

## 1. 这一轮建议训什么

首轮建议先用两类来源：

1. `project_task_synthesis_build` 产出的项目级样本；
2. 如果你已经生成了蒸馏样本，再把 `distillation_export_build` 产出的目录一起作为 `learning_dir`。

这会让首轮同时覆盖：

- 项目结构理解；
- 架构摘要；
- 符号定位；
- 证据检索；
- 可选的教师增强样本。

## 2. 推荐最短路径

```text
project_task_runs / distillation_runs
  -> first_training_round_plan
  -> training_prepare
  -> backup_model_train launch=false
  -> training_server_preflight
  -> 把准备好的 job 放到服务器上显式启动
```

`first_training_round_plan` 只是计划器，不会偷偷训练。它会把你应该依次执行的两个动作写清楚：

1. `training_prepare`
2. `backup_model_train`

## 3. 先生成第一轮计划

```json
{"type":"action","action":"first_training_round_plan","args":{"name":"first-round","learning_dirs":["./project_task_runs/demo","./distillation_runs/demo"],"solution_dirs":[],"training_output_dir":"./training_runs/first-round","model_output_dir":"./model_runs/first-round","base_model":"deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B","include_protocol_examples":true,"min_train_examples":20}}
```

如果你暂时还没有蒸馏样本，就先只放 `project_task_runs/...`，后续第二轮再把蒸馏样本并进来。

## 4. 真正开训前要看什么

在服务器启动前，至少确认：

- `training_runs/.../sample_quality_report.json` 不是低分；
- `dataset_snapshot_manifest.json` 已生成；
- `model_runs/.../data_gate.json` 通过；
- `model_runs/.../training_environment.json` 显示 CUDA 与依赖都可用；
- `training_server_preflight` 通过，且没有别人正在占用 GPU；
- `launch_command.txt` 指向的基座模型和输出目录是你想要的。

共享服务器上先运行：

```json
{"type":"action","action":"training_server_preflight","args":{}}
```

默认策略是 `shared_conservative`：

- 只认 1 张 GPU；
- 如果已经看到其他 compute process，则不启动；
- 如果 GPU 利用率、已用显存或剩余显存不满足阈值，也不启动；
- `launch_command.txt` 会自动走 `safe_launcher`，即使你忘了手动看一次，也会在真正训练前再挡一道。

## 5. 为什么第一轮不要一开始就太大

第一轮最容易暴露的通常不是“模型不够大”，而是：

- 样本任务配比不平衡；
- 证据约束没守住；
- 环境依赖和训练脚本还有缝；
- 评测闭环还没完全吻合。

所以第一轮先做小、做透明、做可复盘。等链路跑通，再扩大语料、加蒸馏、做 ablation，收益会更稳。
