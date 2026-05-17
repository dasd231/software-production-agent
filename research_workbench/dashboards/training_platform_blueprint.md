# 训练平台蓝图

生成时间：`2026-05-17T11:01:00+00:00`

- 北极星：Transparent, adjustable and research-comparable training for project-level models.
- 当前路线：`B`
- 当前 Plane：`distillation_plane`
- 下一批建设：teacher_prompt_batch, teacher_execution_plan, teacher_output_review, distillation_export

## 路线记忆

- A: build the platform top level first
- B: add distillation next
- C: thicken paper-grade comparison after that

## 四大 Plane

| Plane | Purpose | State | Owns |
| --- | --- | --- | --- |
| `distillation_plane` | Absorb capabilities from stronger external or internal teacher models. | active_build | teacher registry, teacher task suite, distillation datasets, teacher output quality gates |
| `corpus_intelligence_plane` | Turn internet repositories into governed, labeled and re-samplable project assets. | foundation_exists | crawler, repo labels, quality taxonomy, provenance and dedup |
| `training_studio_plane` | Expose transparent, adjustable recipes, knobs and ablations to the researcher. | active_build | training recipes, knob registry, ablation plans, experiment cards |
| `benchmark_research_plane` | Compare against internal baselines, market models and paper claims under shared metrics. | skeleton_exists | benchmark registry, external model registry, paper claim matrix, comparison dashboards |

## 关键旋钮

| Knob | Meaning | Affects |
| --- | --- | --- |
| `objective` | What signal the model optimizes against. | capability_target, loss, dataset_shape |
| `base_model` | The starting model before any adaptation. | ceiling, cost, serving_compatibility |
| `task_mix` | How much weight each capability slice receives. | capability_balance, regression_risk |
| `data_mix` | How training examples are sourced across corpora or builders. | coverage, license_risk, generalization |
| `teacher_mix` | Which teacher models contribute supervision when distillation is enabled. | quality, cost, style_bias |
| `context_window` | Prompt budget used by the model or reader. | latency, memory, long_context_behavior |
| `adapter_method` | How parameters are updated. | gpu_memory, trainable_parameters, merge_strategy |
| `evaluation_suite` | What benchmark set gates the experiment. | promotion_gate, paper_comparability |

## 读法

- 这个页面固定四项硬能力与 A→B→C 路线，不让后续开发漂移。
- `training_recipe` 与 `ablation_plan` 属于 Training Studio Plane；它们先于蒸馏链落地，是为了让后续实验可解释、可比较。
