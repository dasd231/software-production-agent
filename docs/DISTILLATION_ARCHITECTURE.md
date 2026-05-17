# 蒸馏架构

蒸馏链的目标不是“多调用几个强模型”，而是把外部模型能力转化为**可追溯、可筛选、可复用**的训练资产。

## 1. 关键对象

| 对象 | 作用 |
| --- | --- |
| `teacher_model_spec.v1` | 描述谁可以做教师 |
| `teacher_task_suite.v1` | 描述教师要教哪些能力 |
| `distillation_plan.v1` | 描述学生、教师配比、共识策略和接收门槛 |
| `teacher_prompt_batch.v1` | 把受治理源样本转成带证据的教师 prompt 批次 |
| `teacher_execution_plan.v1` | 描述将要调用哪些教师、默认是否只 dry-run |
| `teacher_output_review.v1` | 依据 prompt 证据审查教师输出是否可接受 |
| `distillation_dataset_manifest.v1` | 汇总教师输出质量与数据集状态 |
| `distillation_export_manifest.v1` | 把通过审查的教师输出导成可训练样本目录 |

## 2. 基本链路

```text
teacher registry
  -> teacher task suite
  -> distillation plan
  -> teacher prompt batch
  -> teacher execution plan
  -> teacher outputs
  -> teacher output review
  -> distillation dataset manifest
  -> distillation export
  -> training_prepare / training_recipe
```

## 3. 当前设计原则

- 蒸馏先是控制面，再是昂贵调用面；
- 所有教师输出都必须尽量带证据；
- 教师 mix、任务 mix 和接收阈值都必须显式；
- 多教师一致性是可选策略，不应被藏进脚本；
- 教师调用默认先走 `dry_run`，只有操作者显式允许远端调用时才进入昂贵执行；
- 蒸馏产物最终要回到 `training_recipe` 与既有训练控制面中。

## 4. 当前教师目录

当前第一版 teacher catalog 先保留三类角色：

- 高质量远端 reasoning teacher；
- 成本较低的远端 reasoning teacher；
- 私有/本地主教师。

它们现在仍然只是**契约描述**。区别在于，契约之后已经接上了 prompt、执行预览、审查和导出，不再只是目录。

## 5. 当前已经能做什么

当前链路已经能：

1. 从项目级源样本构造带证据的教师 prompt；
2. 在默认不发请求的前提下预览教师执行计划；
3. 检查教师输出是否引用了 prompt 内允许的证据；
4. 把通过审查的输出导成 `training_prepare` 可直接读取的 `training_examples.jsonl`。

## 6. 与下一阶段的关系

下一步最自然的是：

1. 接入真实 teacher runtime adapter；
2. 增加多教师 consensus 与 disagreement review；
3. 把导出后的样本自动串到 ablation / benchmark；
4. 做“无蒸馏 vs 单教师 vs 多教师”的论文级比较。
