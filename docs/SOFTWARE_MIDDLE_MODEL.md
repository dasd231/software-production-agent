# Software Middle-Layer Small Model

This module isolates the small-model seam for expensive software-production rules.

Chinese intent: 这里是给 `software-production-agent` 独立出来的“中间层小模型”模块，用来学习和替代一部分费时的算法/规则判断。它默认 CPU-only，不启动训练，不抢 GPU；先固定接口和安全回退，后续可以替换成你训练的小模型。

## Why this module exists

Many current workflows rely on deterministic but potentially slow rules:

- evidence selection and reranking
- GitHub repo routing
- benchmark triage
- model routing/admission pre-checks
- expensive verification chains

The middle-layer small model should learn when it is safe to shortcut, rerank, or defer those rules.

## Package

```text
agent/software_middle_model/
  __init__.py
  schema.py        # input schema and normalized signals
  accelerator.py   # CPU-only deterministic fallback decision
  program.py       # roadmap and integration contract
```

## Actions

### `software_middle_model_plan`

Read-only planning action.

```json
{"type":"action","action":"software_middle_model_plan","args":{"target":"rule_acceleration"}}
```

### `software_middle_model_decide`

Side-effect-free decision action.

```json
{
  "type": "action",
  "action": "software_middle_model_decide",
  "args": {
    "task": "evidence_selection",
    "features": {"risk": "low"},
    "candidates": [
      {"id": "fast_candidate", "quality_score": 0.92, "rule_cost_ms": 30},
      {"id": "slow_rule", "quality_score": 0.75, "rule_cost_ms": 400}
    ],
    "confidence_threshold": 0.78,
    "margin_threshold": 0.12,
    "rule_budget_ms": 250
  }
}
```

Return contract:

```json
{
  "schema": "software_middle_model_decision.v1",
  "decision": {
    "recommended_mode": "small_model_shortcut | hybrid_verify_top_k | run_expensive_rules",
    "should_run_expensive_rules": false,
    "selected_candidate_id": "fast_candidate",
    "confidence": 0.91,
    "reason": "high_confidence_low_risk_shortcut"
  },
  "ranked_candidates": []
}
```

## Safety policy

The module never claims final authority for high-risk tasks.

It recommends running expensive rules when:

- `features.risk` is high/critical
- `features.safety_critical` is true
- `features.security_sensitive` is true
- `features.requires_exactness` is true
- confidence is below threshold
- top candidate margin is too small
- no candidates are supplied

## Training path

First collect traces from this interface:

```text
input features + candidates
selected candidate
whether expensive rules were run
final accepted outcome
latency saved
quality delta
user satisfaction
benchmark failure/success
```

Then train a small model for:

```text
candidate ranking
shortcut / fallback classification
cost-aware decision making
```

Recommended first models:

```text
logistic regression / linear ranker
LightGBM-style tabular ranker
tiny transformer over normalized decision records
```

## What to replace later

Keep this public contract stable:

```python
from agent.software_middle_model import MiddleModelInput, decide_with_middle_model
```

Later, replace the deterministic scorer inside `accelerator.py` with your trained model backend while preserving:

- input schema
- output schema
- confidence/margin/reason fields
- high-risk fallback behavior
