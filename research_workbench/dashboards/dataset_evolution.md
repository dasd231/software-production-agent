# 数据集演进

生成时间：`2026-05-17T10:46:36+00:00`

## 汇总

- 数据集数：`4`
- 配比健康：`1`
- 仍需关注：`3`

## 关键观察

- grounded supervision improved from 1 to 10 examples
- best-balanced dataset is protocol_rebalanced_20260516 with min_task_share=0.0625
- best-balanced dataset already has a candidate model prepared

## 数据集序列

| Training Run | Accepted | Grounded | Action Protocol | Min Share | Balance | Model Runs |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `protocol_hardmix_20260516` | 103 | 1 | 34 | 0.0097 | watch | backup_qwen_protocol_hardmix_20260516 |
| `protocol_mix_20260516` | 91 | 1 | 22 | 0.011 | watch | backup_protocol_mix_20260516, backup_qwen_protocol_20260516 |
| `protocol_rebalanced_20260516` | 112 | 10 | 34 | 0.0625 | ok | backup_qwen_grounding_rebalanced_20260516 |
| `quality_training_20260515` | 69 | 1 | 0 | 0.0145 | watch | backup_quality_20260515 |

## 读法

- 这个页面更适合做研究复盘：先看数据怎么变，再看模型是否已经跟上验证。
- 如果数据集配比已经修正，但模型仍停留在候选或未评测状态，当前缺的是实验闭环，不是继续改数据。
