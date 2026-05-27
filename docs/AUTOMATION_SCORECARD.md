# Automation Scorecard

这个模块对应待办里的“评价指标：补充实验”。

目标不是生成好看的指标，而是生成能扛住答辩/竞赛/面试拷问的实验协议：

```text
指标定义
  -> 分母规则
  -> 必须出示的证据
  -> 死亡阈值
  -> 反作弊规则
  -> 稀疏证据审查
```

入口：

```text
agent/evaluation/automation_scorecard.py
tests/test_automation_scorecard.py
```

executor action：

```json
{
  "type": "action",
  "action": "automation_scorecard_plan",
  "args": {
    "demand_count": 10,
    "observation_days": 30,
    "output_path": "plans/scorecard.json",
    "evidence": {
      "includes_agent_failures": true,
      "ci_includes_tests": true,
      "third_party_test_review": true,
      "cost_includes_human_review": true
    }
  }
}
```

权限要求：

```text
evaluation:plan + workspace:write
```

## 覆盖维度

- 交付效能：DTR、首次 CI 通过率、回环次数
- 产出质量：缺陷逃逸率、测试覆盖率增量
- 链路可靠性：端到端成功率、幻觉污染率
- 成本效益：单需求综合成本
- 可观测可控：决策可追溯率、人工介入深度
- 知识资产：方案库复用率
- 北极星：有效自动化率

## 反作弊规则

默认强制三条：

1. 所有“率”的分母必须包含 Agent 失败/转人工需求。
2. Agent 自己写的测试必须有第三方盲审有效性抽样。
3. 成本必须包含 token、算力、人工复核、理解损耗、返工。

## 当前边界

当前模块生成 scorecard 和稀疏 evidence review。下一步应接真实 `.agent_events.jsonl`、CI 日志、缺陷 tracker、人工评审表和成本账本，形成自动报表。

