# 训练平台蓝图

这份文档把当前项目的训练方向提升为四个一级能力面。  
它们不是四个零散功能，而是后续“项目大模型”长期演进的正式边界。

## 1. 四个 Plane

| Plane | 负责什么 |
| --- | --- |
| Distillation Plane | 向外部/内部强教师模型学习 |
| Corpus Intelligence Plane | 把互联网项目转成可治理、可打标签、可重采样的语料资产 |
| Training Studio Plane | 让训练设计对研究者透明、可调、可复现实验 |
| Benchmark & Research Plane | 与内部基线、市场模型、论文结果同口径比较 |

```text
Training Platform
├── Distillation Plane
│   ├── teacher registry
│   ├── teacher task suite
│   └── distillation dataset builder
│
├── Corpus Intelligence Plane
│   ├── crawler / repo profiler
│   ├── project labels
│   └── provenance / license / dedup
│
├── Training Studio Plane
│   ├── training_recipe
│   ├── training_knob_registry
│   └── ablation_plan
│
└── Benchmark & Research Plane
    ├── benchmark registry
    ├── external model registry
    └── paper claim matrix
```

## 2. 三条路线

当前路线固定为：

1. **A：先做训练平台顶层结构**；
2. **B：再做蒸馏链**；
3. **C：最后把论文级比较系统做厚**。

当前已经从 A 进入 B。  
A 已经完成了 `training_recipe` 与 `ablation_plan` 的首批基础设施；B 开始补 teacher registry、teacher task suite 与 distillation plan。

## 3. 为什么需要 Training Studio

原有 `training_job_spec` 很适合 runner，它回答的是：

> 这一单具体怎么跑。

但它不适合承担研究设计本身。  
研究者还需要回答：

- 这次训练想验证什么；
- 为什么选这个基座；
- 任务配比为什么这样设；
- 哪些参数是可调旋钮；
- 这次实验相对 baseline 到底只改了什么。

因此新增两类更靠上的对象：

| 对象 | 作用 |
| --- | --- |
| `training_recipe.v1` | 人类可读的训练设计说明书 |
| `ablation_plan.v1` | 变量控制和实验比较说明书 |

## 4. `training_recipe`

一份 recipe 至少表达：

- `research_question`
- `base_model`
- `objective`
- `task_mix`
- `data_mix`
- `teacher_mix`
- `method`
- `evaluation_suite`
- `knobs`

它和 `training_job_spec` 的关系是：

```text
training_recipe
  -> dataset / model / method decisions
  -> training_job_spec
  -> concrete runner execution
```

## 5. `ablation_plan`

一份 ablation plan 至少表达：

- baseline recipe；
- variant recipes；
- 每个 variant 相对 baseline 改了哪些路径；
- 主指标；
- 成功标准。

这样论文中最常见的三类问题可以直接从系统回答：

1. 提升来自哪一个改动；
2. 改了几个变量；
3. 评价是不是同口径。

## 6. 这轮实现的意义

完成这一层后，后续三个方向都能更稳地接进来：

- 做蒸馏时，`teacher_mix` 和 `distillation_sft` 进入 recipe；
- 做互联网语料时，`data_mix` 与 corpus labels 进入 recipe；
- 做论文比较时，benchmark suite 与 ablation 直接形成可复现证据。

这让后面的系统不是“功能越多越乱”，而是“能力越多越容易解释”。
