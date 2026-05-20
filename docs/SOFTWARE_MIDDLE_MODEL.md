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
  traces.py        # JSONL trace records for future supervised training
  program.py       # roadmap and integration contract
```



## Server one-command bootstrap

If the server does not yet have enough real middle-model traces, use this once to create a smoke-training package.  It generates synthetic bootstrap traces only for validating the training path; do not use the result as a final model-quality claim.

```bash
python -m agent.software_middle_model.cli bootstrap-first-round \
  --output-root /data/ThreadModel/software_middle_first \
  --min-traces 8 \
  --adapter-name software-middle-model-lora \
  --max-seq-length 1024 \
  --cpu-threads 4 \
  --max-gpu-memory-gb 12
```

Then read:

```bash
cat /data/ThreadModel/software_middle_first/model_runs/software-middle-first/SERVER_HANDOFF.md
```

Dry-run on the server:

```bash
python -m agent.training.backup_trainer \
  --config /data/ThreadModel/software_middle_first/model_runs/software-middle-first/backup_training_spec.json \
  --dry-run
```

Only launch after `nvidia-smi` is idle and the shared-server preflight is admitted:

```bash
python -m agent.training.backup_trainer \
  --config /data/ThreadModel/software_middle_first/model_runs/software-middle-first/backup_training_spec.json
```
## CLI quick path

Once traces exist, the first server-ready package can be prepared without writing action JSON.

```bash
python -m agent.software_middle_model.cli export-dataset \
  --trace-path middle_model/traces.jsonl \
  --output-dir training_runs/software-middle-first \
  --min-traces 1 \
  --eval-ratio 0.15

python -m agent.software_middle_model.cli server-handoff \
  --training-dir training_runs/software-middle-first \
  --output-dir model_runs/software-middle-first \
  --adapter-name software-middle-model-lora \
  --min-train-examples 1 \
  --max-seq-length 1024
```

Then move/sync the repo plus `training_runs/software-middle-first` and `model_runs/software-middle-first` to the GPU server.  On the server, read `model_runs/software-middle-first/SERVER_HANDOFF.md`, run the preflight, run dry-run, and only then launch.
## Actions

### `software_middle_model_plan`

Read-only planning action.

```json
{"type":"action","action":"software_middle_model_plan","args":{"target":"rule_acceleration"}}
```

### `software_middle_model_decide`

Decision action. It is side-effect-free by default; if `trace_output_path` is provided, it also appends one JSONL trace record under the workspace.

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
    "rule_budget_ms": 250,
    "trace_output_path": "middle_model/traces.jsonl",
    "final_accepted": true,
    "latency_saved_ms": 100,
    "quality_delta": 0.0,
    "source_trace_id": "run-001",
    "outcome": {"grade": "accepted"}
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



### `software_middle_model_dataset_export`

Export JSONL traces into the first train/eval dataset that `backup_model_train` can consume.

```json
{
  "type": "action",
  "action": "software_middle_model_dataset_export",
  "args": {
    "trace_paths": ["middle_model/traces.jsonl"],
    "output_dir": "training_runs/software-middle-first",
    "base_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
    "eval_ratio": 0.15,
    "min_traces": 1,
    "max_examples": 2000
  }
}
```

Outputs:

```text
training_runs/software-middle-first/
  dataset.jsonl
  train.jsonl
  eval.jsonl
  raw_examples.jsonl
  data_card.md
  quality_report.json
  sample_quality_report.json
  governance_report.json
  training_plan.json
  dataset_snapshot_manifest.json
  middle_model_dataset_manifest.json
```

### `software_middle_model_server_handoff`

Prepare the first server training package without launching training.

```json
{
  "type": "action",
  "action": "software_middle_model_server_handoff",
  "args": {
    "training_dir": "training_runs/software-middle-first",
    "output_dir": "model_runs/software-middle-first",
    "base_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
    "adapter_name": "software-middle-model-lora",
    "min_train_examples": 1,
    "max_seq_length": 1024,
    "cpu_threads": 4,
    "max_gpu_memory_gb": 12.0
  }
}
```

Outputs:

```text
model_runs/software-middle-first/
  backup_training_spec.json
  training_job_spec.json
  training_job_manifest.json
  launch_command.txt
  training_resource_policy.json
  server_preflight_action.json
  SERVER_HANDOFF.md
  software_middle_model_server_handoff.json
```

Server launch remains manual by design:

```bash
python -m agent.training.backup_trainer --config model_runs/software-middle-first/backup_training_spec.json --dry-run
# only after shared-server preflight passes:
python -m agent.training.backup_trainer --config model_runs/software-middle-first/backup_training_spec.json
```
## Trace collection

The first practical job for this module is data accumulation.  Every accepted or rejected shortcut can become a future supervised example.

Python API:

```python
from agent.software_middle_model import (
    build_middle_model_trace,
    append_middle_model_trace,
    load_middle_model_traces,
)
```

Trace JSONL schema:

```json
{
  "schema": "software_middle_model_trace.v1",
  "trace_id": "uuid",
  "source_trace_id": "run-001",
  "task": "evidence_selection",
  "features": {},
  "candidates": [],
  "decision": {},
  "ranked_candidates": [],
  "labels": {
    "final_accepted": true,
    "shortcut_success": true,
    "selected_candidate_id": "fast_candidate",
    "should_run_expensive_rules": false,
    "latency_saved_ms": 100.0,
    "quality_delta": 0.0
  }
}
```

Keep traces small and auditable.  Do not store secrets, private code, or large raw documents in middle-model traces.
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




