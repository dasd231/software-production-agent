# 训练证据谱系

生成时间：`2026-05-17T10:18:32+00:00`

## `dataset-1e4c574e483686c6385a924e`

- 训练数据 run：`protocol_hardmix_20260516`
- 质量：`9.66` excellent
- 任务配比：action_protocol_sft:34, code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:1, solution_reuse_sft:7

| Model Run | Model Version | Base Model | Job | Eval Count | Promotion |
| --- | --- | --- | --- | ---: | --- |
| `backup_qwen_protocol_hardmix_20260516` | `backup-6cc03ce09f7d72204aba` | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | completed | 2 | blocked |

## `dataset-ccd957c9b2d5f2887280ff92`

- 训练数据 run：`protocol_mix_20260516`
- 质量：`9.39` excellent
- 任务配比：action_protocol_sft:22, code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:1, solution_reuse_sft:7

| Model Run | Model Version | Base Model | Job | Eval Count | Promotion |
| --- | --- | --- | --- | ---: | --- |
| `backup_protocol_mix_20260516` | `backup-f4a25b2403a8832a2c01` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` | completed | 1 | blocked |
| `backup_qwen_protocol_20260516` | `backup-08e1a18c01536ed4f030` | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | completed | 2 | blocked |

## `dataset-0f1cc25c95e3a85ab41e3b3c`

- 训练数据 run：`protocol_rebalanced_20260516`
- 质量：`9.65` excellent
- 任务配比：action_protocol_sft:34, code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:10, solution_reuse_sft:7

| Model Run | Model Version | Base Model | Job | Eval Count | Promotion |
| --- | --- | --- | --- | ---: | --- |
| `backup_qwen_grounding_rebalanced_20260516` | `backup-9a99a769dbbecdf10410` | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | queued | 0 |  |

## `dataset-6f447ebebbe5f1e5d3ad24c9`

- 训练数据 run：`quality_training_20260515`
- 质量：`9.2` excellent
- 任务配比：code_explanation:31, knowledge_card_qa:30, rag_grounded_answer:1, solution_reuse_sft:7

| Model Run | Model Version | Base Model | Job | Eval Count | Promotion |
| --- | --- | --- | --- | ---: | --- |
| `backup_quality_20260515` | `backup-0f098e6989aa068e720f` | `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` | completed | 0 |  |

## 基线评测

| Eval | Label | Benchmark | Overall |
| --- | --- | --- | ---: |
| `base_20260516` | `base` | backup_model_eval.v1.json | 7.22 |
| `base_20260516_benchv2` | `base_benchv2` | backup_model_eval.v2.json | 6.16 |
| `base_20260516_benchv2_schema` | `base_benchv2_schema` | backup_model_eval.v2.json | 6.16 |
| `base_20260516_v2` | `base` | backup_model_eval.v1.json | 6.83 |
| `qwen25coder_base_20260516_benchv2` | `qwen25coder_base_benchv2` | backup_model_eval.v2.json | 6.76 |
| `qwen25coder_base_20260516_benchv2_schema` | `qwen25coder_base_benchv2_schema` | backup_model_eval.v2.json | 8.02 |
| `qwen25coder_base_20260516_benchv3` | `qwen25coder_base_benchv3` | backup_model_eval.v3.json | 8.41 |

## 尚未精确挂接的候选评测

| Eval | Label | Benchmark | Overall |
| --- | --- | --- | ---: |
| `tuned_20260516` | `tuned` | backup_model_eval.v1.json | 7.29 |
| `tuned_20260516_v2` | `tuned` | backup_model_eval.v1.json | 6.69 |
| `tuned_old_20260516_benchv2` | `tuned_old_benchv2` | backup_model_eval.v2.json | 6.39 |

## 尚未精确挂接的晋级决策

| Decision | Label | Benchmark | Status |
| --- | --- | --- | --- |

## 说明

- 训练数据到模型训练的链路来自 dataset_snapshot_id 的精确引用。
- baseline 评测不应挂到 adapter 版本上，会单独保留在 baseline_evaluations 中。
- 候选模型评测只有在 report.subject.model_version 存在时才会被精确挂接；缺少引用的候选评测会保留在 unlinked_candidate_evaluations 中。
- 晋级决策只有在 candidate.model_version 存在时才会被精确挂接；缺少模型版本引用的决策会保留在 unlinked_promotion_decisions 中。
