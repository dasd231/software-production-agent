# 备用模型评测

训练完成并不等于模型已经有价值。为了验证备用模型是否真的继承了项目能力，系统引入三类轻量但可审计的基准：

| 维度 | 验证问题 |
| --- | --- |
| `action_protocol` | 是否能输出合法且符合预期的 action JSON |
| `grounded_answer` | 是否能依据给定证据回答，并保留引用 |
| `solution_reuse` | 是否能从历史方案中提炼关键交付物和复用原则 |

当前提供两版基准：

| 文件 | 用途 |
| --- | --- |
| `benchmarks/backup_model_eval.v1.json` | 第一版种子基准，用于快速打通工程闭环 |
| `benchmarks/backup_model_eval.v2.json` | 更严格的混合基准，既测协议，也隐含测一部分工具选择 |
| `benchmarks/backup_model_eval.v3.json` | 协议纯净基准：prompt 明确给出目标 action，只测 schema 服从，不混入工具选择 |

`v2` 的设计动机来自首轮实验：基座模型和第一版 adapter 都能在部分知识问答上得分，但几乎不会稳定输出合法 action JSON，因此必须把“像 Agent 一样行动”单独测出来，而不能让它被长文本问答分数掩盖。后续实验进一步表明，协议服从与工具选择是两类不同能力，因此新增 `v3` 作为更干净的协议评测基准。

对 `action_protocol` 类样例，评测脚本会注入真实运行时使用的 `system.txt + action.txt`，因此测到的是“模型拿到正式协议说明后是否遵守”，而不是要求模型凭空背出项目私有 schema。

## 运行方式

先评估基座模型：

```powershell
$env:PYTHONPATH='.'
.\.venv-train\Scripts\python.exe -m agent.training.backup_eval `
  --benchmark .\benchmarks\backup_model_eval.v3.json `
  --base-model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B `
  --output-dir .\model_evals\base_20260516 `
  --label base
```

再评估训练后的 adapter：

```powershell
$env:PYTHONPATH='.'
.\.venv-train\Scripts\python.exe -m agent.training.backup_eval `
  --benchmark .\benchmarks\backup_model_eval.v3.json `
  --base-model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B `
  --adapter-dir .\model_runs\backup_quality_20260515\adapter `
  --output-dir .\model_evals\tuned_20260516 `
  --label tuned `
  --compare-base .\model_evals\base_20260516\model_evaluation_report.json
```

每次评测都会输出：

- `predictions.jsonl`
- `model_evaluation_report.json`
- `report.md`
- 对照组还会额外输出 `comparison_vs_base.json`

资源中心会自动把 `model_evaluation_report.json` 识别为 `model_evaluation` 资源。

新的评测报告还会显式记录 `subject.subject_type`：

| 类型 | 含义 |
| --- | --- |
| `base_model` | 直接评测基座模型 |
| `model_version` | 评测已登记的候选模型版本 |
| `untracked_adapter` | 评测了 adapter，但尚未绑定正式模型版本 |

这样后续谱系分析不再需要只靠 label 猜测“这是 baseline 还是候选模型”。

## 评测后的晋级门禁

训练闭环不应该停在“有一份评测报告”。  
在候选 adapter 与同一基准上的 baseline 都完成评测后，可以生成一个独立的晋级判断：

```powershell
$env:PYTHONPATH='.'
.\.venv-train\Scripts\python.exe -m agent.training.promotion `
  --baseline-report .\model_evals\backup-demo-base-benchv3\model_evaluation_report.json `
  --candidate-report .\model_evals\backup-demo-tuned-benchv3\model_evaluation_report.json `
  --model-version-manifest .\model_runs\backup-demo\model_version_manifest.json `
  --output-dir .\model_evals\backup-demo-tuned-benchv3
```

它会额外输出：

- `model_promotion_decision.json`
- `promotion_report.md`

默认门禁会检查：

1. baseline 与 candidate 是否使用同一 benchmark；
2. candidate 是否达到最低总分；
3. candidate 是否至少不低于 baseline；
4. `action_protocol`、`grounded_answer`、`solution_reuse` 三项是否都达到最低分；
5. candidate 评测是否确实挂接到指定的 `model_version_manifest`。

通过门禁只表示进入 `ready_for_manual_review`，**不是自动替换主模型**。  
它的作用是把“是否值得继续人工评审”固化成可复查产物，而不是让人每次手工比对多份 JSON。

如果门禁未通过，决策中还会附带 `recommended_actions`，例如：

- `increase_action_protocol_supervision`
- `rebalance_grounded_answer_supervision`
- `run_regression_focused_ablation`

这让下一轮训练不只知道“没过”，还知道优先应该补哪类能力。

如果 candidate 报告需要和 `model_version_manifest` 精确挂接，候选模型评测应使用上一节示例中的 `--model-version-manifest` 重新生成；旧评测报告没有 `subject.model_version` 时，门禁会故意阻塞。

## 评测解释

当前模型评测应至少回答三件事：

1. `action_protocol` 是否从 0 分起步，真正学会输出合法动作；
2. `grounded_answer` 是否在补协议能力时仍能维持证据忠实；
3. `solution_reuse` 是否因数据配比失衡而退化。

只有三项同时稳定，adapter 才具备继续扩大训练或进入灰度验证的意义。
