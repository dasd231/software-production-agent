# 实验对比

生成时间：`2026-05-17T10:06:52+00:00`

## backup_model_eval.v1.json

- 基线：`base` / `7.22`
- 当前最好：`tuned` / `7.29`

| Eval | Label | Overall | Grade | Δ vs baseline |
| --- | --- | ---: | --- | ---: |
| `tuned_20260516` | `tuned` | 7.29 | good | 0.07 |
| `base_20260516` | `base` | 7.22 | good | 0.0 |
| `base_20260516_v2` | `base` | 6.83 | good | -0.39 |
| `tuned_20260516_v2` | `tuned` | 6.69 | good | -0.53 |

## backup_model_eval.v2.json

- 基线：`qwen25coder_base_benchv2_schema` / `8.02`
- 当前最好：`qwen25coder_tuned_protocol_benchv2_schema` / `8.02`

| Eval | Label | Overall | Grade | Δ vs baseline |
| --- | --- | ---: | --- | ---: |
| `qwen25coder_tuned_protocol_20260516_benchv2_schema` | `qwen25coder_tuned_protocol_benchv2_schema` | 8.02 | excellent | 0.0 |
| `qwen25coder_base_20260516_benchv2_schema` | `qwen25coder_base_benchv2_schema` | 8.02 | excellent | 0.0 |
| `qwen25coder_tuned_hardmix_20260516_benchv2_schema` | `qwen25coder_tuned_hardmix_benchv2_schema` | 7.73 | good | -0.29 |
| `tuned_protocol_20260516_benchv2` | `tuned_protocol_benchv2` | 7.16 | good | -0.86 |
| `qwen25coder_tuned_protocol_20260516_benchv2` | `qwen25coder_tuned_protocol_benchv2` | 6.76 | good | -1.26 |
| `qwen25coder_base_20260516_benchv2` | `qwen25coder_base_benchv2` | 6.76 | good | -1.26 |
| `tuned_old_20260516_benchv2` | `tuned_old_benchv2` | 6.39 | watch | -1.63 |
| `base_20260516_benchv2_schema` | `base_benchv2_schema` | 6.16 | watch | -1.86 |
| `base_20260516_benchv2` | `base_benchv2` | 6.16 | watch | -1.86 |

## backup_model_eval.v3.json

- 基线：`qwen25coder_base_benchv3` / `8.41`
- 当前最好：`qwen25coder_base_benchv3` / `8.41`

| Eval | Label | Overall | Grade | Δ vs baseline |
| --- | --- | ---: | --- | ---: |
| `qwen25coder_base_20260516_benchv3` | `qwen25coder_base_benchv3` | 8.41 | excellent | 0.0 |
| `qwen25coder_tuned_hardmix_20260516_benchv3` | `qwen25coder_tuned_hardmix_benchv3` | 7.94 | good | -0.47 |

## 使用说明

- 这个页面适合做 baseline / variant / tuned 模型的快速横向比较。
- 只有在 benchmark 一致时，Δ 才适合进入正式结论。
