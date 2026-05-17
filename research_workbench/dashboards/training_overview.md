# 训练总览

生成时间：`2026-05-17T04:57:59+00:00`

## 汇总

- 训练数据 run：`4`
- 模型训练 run：`5`
- 模型评测 run：`15`
- 晋级决策 run：`5`
- 任务配比需关注的数据集：`3`

## 最近训练数据

| Run | Dataset | Examples | Quality | Min Share | Balance | Task Mix |
| --- | --- | ---: | --- | ---: | --- | --- |
| `protocol_hardmix_20260516` | `dataset-1e4c574e483686c6385a924e` | 103 | 9.66 excellent | 0.0097 | watch | action_protocol_sft:34, code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:1, solution_reuse_sft:7 |
| `protocol_mix_20260516` | `dataset-ccd957c9b2d5f2887280ff92` | 91 | 9.39 excellent | 0.011 | watch | action_protocol_sft:22, code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:1, solution_reuse_sft:7 |
| `protocol_rebalanced_20260516` | `dataset-0f1cc25c95e3a85ab41e3b3c` | 112 | 9.65 excellent | 0.0625 | ok | action_protocol_sft:34, code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:10, solution_reuse_sft:7 |
| `quality_training_20260515` | `dataset-6f447ebebbe5f1e5d3ad24c9` | 69 | 9.2 excellent | 0.0145 | watch | code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:1, solution_reuse_sft:7 |

## 最近模型训练

| Run | Base Model | Stage | Job | Train Loss | Eval Loss |
| --- | --- | --- | --- | ---: | ---: |
| `backup_protocol_mix_20260516` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` | trained | completed | 3.078549861907959 | 2.6299993991851807 |
| `backup_quality_20260515` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` | trained | completed | 2.8838601112365723 | 2.8430511951446533 |
| `backup_qwen_grounding_rebalanced_20260516` | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | candidate | queued | None | None |
| `backup_qwen_protocol_20260516` | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | trained | completed | 2.148988723754883 | 1.6732922792434692 |
| `backup_qwen_protocol_hardmix_20260516` | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | trained | completed | 2.0783119960264727 | 1.6045572757720947 |

## 最近模型评测

| Eval | Label | Overall | Grade | Stage Scores |
| --- | --- | ---: | --- | --- |
| `base_20260516_v2` | `base` | 6.83 | good | action_protocol:0.0, grounded_answer:7.17, solution_reuse:6.24 |
| `qwen25coder_base_20260516_benchv2` | `qwen25coder_base_benchv2` | 6.76 | good | action_protocol:0.0, grounded_answer:7.99, solution_reuse:4.92 |
| `qwen25coder_base_20260516_benchv2_schema` | `qwen25coder_base_benchv2_schema` | 8.02 | excellent | action_protocol:5.81, grounded_answer:7.99, solution_reuse:4.92 |
| `qwen25coder_base_20260516_benchv3` | `qwen25coder_base_benchv3` | 8.41 | excellent | action_protocol:7.5, grounded_answer:7.32, solution_reuse:5.08 |
| `qwen25coder_tuned_hardmix_20260516_benchv2_schema` | `qwen25coder_tuned_hardmix_benchv2_schema` | 7.73 | good | action_protocol:5.88, grounded_answer:6.21, solution_reuse:6.31 |
| `qwen25coder_tuned_hardmix_20260516_benchv3` | `qwen25coder_tuned_hardmix_benchv3` | 7.94 | good | action_protocol:6.25, grounded_answer:4.95, solution_reuse:6.95 |
| `qwen25coder_tuned_protocol_20260516_benchv2` | `qwen25coder_tuned_protocol_benchv2` | 6.76 | good | action_protocol:0.0, grounded_answer:7.1, solution_reuse:5.81 |
| `qwen25coder_tuned_protocol_20260516_benchv2_schema` | `qwen25coder_tuned_protocol_benchv2_schema` | 8.02 | excellent | action_protocol:5.88, grounded_answer:7.1, solution_reuse:5.81 |
| `tuned_20260516` | `tuned` | 7.29 | good | action_protocol:0.0, grounded_answer:8.51, solution_reuse:6.58 |
| `tuned_20260516_v2` | `tuned` | 6.69 | good | action_protocol:0.0, grounded_answer:7.97, solution_reuse:4.41 |
| `tuned_old_20260516_benchv2` | `tuned_old_benchv2` | 6.39 | watch | action_protocol:0.0, grounded_answer:6.1, solution_reuse:5.81 |
| `tuned_protocol_20260516_benchv2` | `tuned_protocol_benchv2` | 7.16 | good | action_protocol:0.0, grounded_answer:7.27, solution_reuse:6.82 |

## 最近晋级决策

| Decision | Label | Benchmark | Status | Next Step |
| --- | --- | --- | --- | --- |
| `qwen25coder_tuned_hardmix_20260516_benchv2_schema` | `qwen25coder_tuned_hardmix_benchv2_schema` | `backup_model_eval.v2.json` | blocked | adjust_data_or_training_then_re_evaluate |
| `qwen25coder_tuned_hardmix_20260516_benchv3` | `qwen25coder_tuned_hardmix_benchv3` | `backup_model_eval.v3.json` | blocked | adjust_data_or_training_then_re_evaluate |
| `qwen25coder_tuned_protocol_20260516_benchv2` | `qwen25coder_tuned_protocol_benchv2` | `backup_model_eval.v2.json` | blocked | adjust_data_or_training_then_re_evaluate |
| `qwen25coder_tuned_protocol_20260516_benchv2_schema` | `qwen25coder_tuned_protocol_benchv2_schema` | `backup_model_eval.v2.json` | blocked | adjust_data_or_training_then_re_evaluate |
| `tuned_protocol_20260516_benchv2` | `tuned_protocol_benchv2` | `backup_model_eval.v2.json` | blocked | adjust_data_or_training_then_re_evaluate |

## 使用说明

- 这个页面只做轻量汇总，不替代正式实验登记。
- 需要形成论文结论时，仍应在 `experiments/experiment_registry.csv` 中登记实验问题、数据、方法和结论。
- 需要复盘同行工作时，使用 `literature/paper_reading_log.csv`。
