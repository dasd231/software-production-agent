# 蒸馏架构

蒸馏链的目标不是“多调用几个强模型”，而是把外部模型能力转化为**可追溯、可筛选、可复用**的训练资产。

## 1. 四个对象

| 对象 | 作用 |
| --- | --- |
| `teacher_model_spec.v1` | 描述谁可以做教师 |
| `teacher_task_suite.v1` | 描述教师要教哪些能力 |
| `distillation_plan.v1` | 描述学生、教师配比、共识策略和接收门槛 |
| `distillation_dataset_manifest.v1` | 描述教师输出如何转成可训样本 |

## 2. 基本链路

```text
teacher registry
  -> teacher task suite
  -> distillation plan
  -> teacher outputs
  -> distillation dataset manifest
  -> training_prepare / training_recipe
```

## 3. 当前设计原则

- 蒸馏先是控制面，再是昂贵调用面；
- 所有教师输出都必须尽量带证据；
- 教师 mix、任务 mix 和接收阈值都必须显式；
- 多教师一致性是可选策略，不应被藏进脚本；
- 蒸馏产物最终要回到 `training_recipe` 与既有训练控制面中。

## 4. 当前教师目录

当前第一版 teacher catalog 先保留三类角色：

- 高质量远端 reasoning teacher；
- 成本较低的远端 reasoning teacher；
- 私有/本地主教师。

它们都只是**契约描述**。真实调用仍应由后续执行层接入，而不是在设计阶段隐式触发 API。

## 5. 与下一阶段的关系

本轮完成后，下一步可以安全地接：

1. 真实 teacher executor；
2. teacher output judge；
3. 多教师 consensus；
4. distillation -> `training_prepare` 的自动转换；
5. 与非蒸馏 baseline 的 ablation。
