"""Fine-tuning preparation sub-chain.

This chain prepares auditable SFT datasets from learning runs and solution
artifacts. It does not launch GPU training; deployment/training remain explicit
operator actions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.evaluation.aggregate import aggregate_metric_reports
from agent.evaluation.governance import evaluate_dataset_governance
from agent.evaluation.sample_quality import review_training_examples
from agent.evaluation.training import evaluate_training_dataset, training_quality_summary
from agent.runtime.manifest import build_run_manifest, write_run_manifest
from agent.training.datasets import create_dataset_snapshot
from agent.training.protocol_examples import build_protocol_examples


@dataclass(frozen=True)
class TrainingPrepareInput:
    output_dir: Path
    learning_dirs: tuple[Path, ...] = ()
    solution_dirs: tuple[Path, ...] = ()
    dataset_format: str = "messages"
    eval_ratio: float = 0.15
    min_chars: int = 20
    max_examples: int = 2000
    model_hint: str = "deepseek"
    include_protocol_examples: bool = True
    protocol_example_limit: int = 0


@dataclass(frozen=True)
class TrainingPrepareResult:
    output_dir: str
    dataset_format: str
    total_examples: int
    train_examples: int
    eval_examples: int
    rejected_examples: int
    files: dict[str, str] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    sample_quality: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    governance: dict[str, Any] = field(default_factory=dict)
    evaluation_summary: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "dataset_format": self.dataset_format,
            "total_examples": self.total_examples,
            "train_examples": self.train_examples,
            "eval_examples": self.eval_examples,
            "rejected_examples": self.rejected_examples,
            "files": self.files,
            "quality": self.quality,
            "plan": self.plan,
            "sample_quality": self.sample_quality,
            "evaluation": self.evaluation,
            "governance": self.governance,
            "evaluation_summary": self.evaluation_summary,
            "manifest": self.manifest,
        }


def _stable_id(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=12)
    for part in parts:
        h.update(str(part).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _safe_read(path: Path, max_chars: int = 6000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _normalise_training_example(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    instruction = str(row.get("instruction", "") or "").strip()
    inp = str(row.get("input", "") or "").strip()
    output = str(row.get("output", "") or "").strip()
    if not instruction or not output:
        return None
    example_id = str(row.get("example_id", "") or "") or _stable_id(source, instruction, inp, output)
    citations = row.get("citations") if isinstance(row.get("citations"), list) else []
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {
        "example_id": example_id,
        "task_type": str(row.get("task_type", "sft")),
        "instruction": instruction,
        "input": inp,
        "output": output,
        "citations": citations,
        "metadata": {**metadata, "source": source},
    }


def _learning_promotion_context(learning_dir: Path) -> dict[str, Any] | None:
    path = learning_dir / "knowledge_promotion.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    promoted_rows = raw.get("promoted") if isinstance(raw.get("promoted"), list) else []
    promoted_repos = {
        str(row.get("repo", ""))
        for row in promoted_rows
        if isinstance(row, dict) and bool(row.get("eligible")) and str(row.get("repo", "")).strip()
    }
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    return {
        "path": str(path),
        "summary": summary,
        "promoted_repos": promoted_repos,
        "schema": str(raw.get("schema", "")),
    }


def _solution_manifest_paths(solution_dirs: tuple[Path, ...], max_files: int = 120) -> list[Path]:
    paths: list[Path] = []
    for root in solution_dirs:
        if not root.exists():
            continue
        if root.is_file() and root.name == "solution_manifest.json":
            paths.append(root)
            continue
        direct = root / "solution_manifest.json"
        if direct.exists():
            paths.append(direct)
        for p in root.glob("*/solution_manifest.json"):
            paths.append(p)
            if len(paths) >= max_files:
                break
        if len(paths) >= max_files:
            break
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out[:max_files]


def _solution_examples(solution_dirs: tuple[Path, ...]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for manifest_path in _solution_manifest_paths(solution_dirs):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        run_dir = manifest_path.parent
        backup_path = run_dir / "docs" / "SOLUTION_BACKUP.md"
        backup = _safe_read(backup_path, max_chars=5000)
        if not backup.strip():
            continue
        tags = raw.get("retrieval_tags") if isinstance(raw.get("retrieval_tags"), list) else []
        artifacts = raw.get("artifact_hints") if isinstance(raw.get("artifact_hints"), list) else []
        goal = str(raw.get("goal", "") or "")
        stack = str(raw.get("stack", "") or "")
        template = str(raw.get("template", "") or "")
        instruction = "根据历史软件方案备份，输出可复用的软件生产方案，必须保留关键交付物和复用边界。"
        inp = (
            f"需求：{goal}\n"
            f"技术栈：{stack}\n"
            f"模板：{template}\n"
            f"复用标签：{', '.join(str(x) for x in tags)}\n"
            f"交付物提示：{', '.join(str(x) for x in artifacts)}"
        )
        examples.append(
            {
                "example_id": _stable_id("solution", str(manifest_path), goal, template),
                "task_type": "solution_reuse_sft",
                "instruction": instruction,
                "input": inp,
                "output": backup,
                "citations": [{"path": str(manifest_path)}, {"path": str(backup_path)}],
                "metadata": {
                    "source": "solution_library",
                    "run_id": run_dir.name,
                    "stack": stack,
                    "template": template,
                },
            }
        )
    return examples


def collect_training_examples(
    learning_dirs: tuple[Path, ...],
    solution_dirs: tuple[Path, ...],
    *,
    include_protocol_examples: bool = True,
    protocol_example_limit: int = 0,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for learning_dir in learning_dirs:
        source = str(learning_dir.resolve())
        promotion = _learning_promotion_context(learning_dir)
        promoted_repos = set(promotion["promoted_repos"]) if promotion else set()
        promoted_count = int((promotion or {}).get("summary", {}).get("promoted", 0) or 0)
        for row in _read_jsonl(learning_dir / "training_examples.jsonl"):
            example = _normalise_training_example(row, source)
            if not example:
                continue
            if promotion:
                metadata = example.get("metadata") if isinstance(example.get("metadata"), dict) else {}
                repo = str(metadata.get("repo", "") or "")
                if promoted_count <= 0:
                    continue
                if repo and repo not in promoted_repos:
                    continue
                example["metadata"] = {
                    **metadata,
                    "knowledge_gate": {
                        "schema": promotion["schema"],
                        "promotion_path": promotion["path"],
                        "promoted_repos": promoted_count,
                    },
                }
            examples.append(example)
    examples.extend(_solution_examples(solution_dirs))
    if include_protocol_examples:
        examples.extend(build_protocol_examples(limit=protocol_example_limit))
    return examples


def _system_prompt(example: dict[str, Any]) -> str:
    task_type = str(example.get("task_type", "") or "")
    if task_type == "action_protocol_sft":
        return "你是软件生产 Agent。必须严格输出一个 action JSON 对象，不得解释、不得展示思考过程。"
    return "你是软件生产 Agent 的可控微调样本，回答必须忠于输入证据。"


def _to_messages(example: dict[str, Any]) -> dict[str, Any]:
    user = str(example.get("instruction", "")).strip()
    inp = str(example.get("input", "")).strip()
    if inp:
        user += "\n\n输入：\n" + inp
    return {
        "messages": [
            {"role": "system", "content": _system_prompt(example)},
            {"role": "user", "content": user},
            {"role": "assistant", "content": str(example.get("output", "")).strip()},
        ],
        "metadata": {
            "example_id": example.get("example_id"),
            "task_type": example.get("task_type"),
            "citations": example.get("citations", []),
            **(example.get("metadata") if isinstance(example.get("metadata"), dict) else {}),
        },
    }


def _to_alpaca(example: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": str(example.get("instruction", "")).strip(),
        "input": str(example.get("input", "")).strip(),
        "output": str(example.get("output", "")).strip(),
        "metadata": {
            "example_id": example.get("example_id"),
            "task_type": example.get("task_type"),
            "citations": example.get("citations", []),
            **(example.get("metadata") if isinstance(example.get("metadata"), dict) else {}),
        },
    }


def _format_example(example: dict[str, Any], dataset_format: str) -> dict[str, Any]:
    if dataset_format == "alpaca":
        return _to_alpaca(example)
    return _to_messages(example)


def _split_examples(examples: list[dict[str, Any]], eval_ratio: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ratio = min(max(float(eval_ratio), 0.0), 0.5)
    if not examples or ratio <= 0:
        return list(examples), []
    eval_count = max(1, int(round(len(examples) * ratio))) if len(examples) > 1 else 0
    by_task: dict[str, list[dict[str, Any]]] = {}
    for example in examples:
        by_task.setdefault(str(example.get("task_type", "unknown") or "unknown"), []).append(example)
    ranked_groups = {
        task: sorted(
            rows,
            key=lambda ex: _stable_id(str(ex.get("example_id", "")), str(ex.get("instruction", ""))),
        )
        for task, rows in by_task.items()
    }
    eval_ids: set[str] = set()

    # First pass: when budget allows, reserve one held-out row for each task type
    # that has at least two examples. This prevents an entire capability slice
    # (for example action_protocol_sft) from accidentally disappearing from eval.
    eligible_groups = [(task, rows) for task, rows in sorted(ranked_groups.items()) if len(rows) > 1]
    for _, rows in eligible_groups[:eval_count]:
        eval_ids.add(str(rows[0].get("example_id", "")))

    # Second pass: fill the remaining budget deterministically from the rest.
    remaining = [
        ex
        for _, rows in sorted(ranked_groups.items())
        for ex in rows
        if str(ex.get("example_id", "")) not in eval_ids
    ]
    remaining.sort(key=lambda ex: _stable_id(str(ex.get("example_id", "")), str(ex.get("instruction", ""))))
    for ex in remaining:
        if len(eval_ids) >= eval_count:
            break
        eval_ids.add(str(ex.get("example_id", "")))
    train = [ex for ex in examples if str(ex.get("example_id", "")) not in eval_ids]
    eval_rows = [ex for ex in examples if str(ex.get("example_id", "")) in eval_ids]
    return train, eval_rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _training_plan(
    *,
    model_hint: str,
    dataset_format: str,
    train_path: Path,
    eval_path: Path,
    train_count: int,
    eval_count: int,
) -> dict[str, Any]:
    base_model = "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct" if "coder" in model_hint.lower() else "deepseek-ai/DeepSeek-V2.5"
    return {
        "status": "prepared_not_started",
        "base_model": base_model,
        "method": "LoRA/QLoRA SFT",
        "dataset_format": dataset_format,
        "train_file": str(train_path),
        "eval_file": str(eval_path),
        "train_examples": train_count,
        "eval_examples": eval_count,
        "recommended_next_steps": [
            "人工抽检 train/eval JSONL，确认无密钥、隐私数据和许可证风险",
            "使用 LLaMA-Factory、Axolotl 或 TRL/SFTTrainer 启动 LoRA/QLoRA 微调",
            "在独立评测集上验证 action JSON 合法率、RAG 引用忠实度和生产任务成功率",
            "通过 vLLM 或兼容服务部署合并或 LoRA adapter 后的模型",
        ],
    }


def prepare_fine_tuning_dataset(inp: TrainingPrepareInput) -> TrainingPrepareResult:
    fmt = inp.dataset_format.strip().lower() or "messages"
    if fmt not in {"messages", "alpaca"}:
        fmt = "messages"
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_examples = collect_training_examples(
        inp.learning_dirs,
        inp.solution_dirs,
        include_protocol_examples=bool(inp.include_protocol_examples),
        protocol_example_limit=max(int(inp.protocol_example_limit), 0),
    )
    examples, rejected, sample_decisions, sample_quality_report = review_training_examples(
        raw_examples,
        min_chars=max(int(inp.min_chars), 1),
        max_examples=max(int(inp.max_examples), 1),
    )
    train_raw, eval_raw = _split_examples(examples, inp.eval_ratio)
    train_rows = [_format_example(ex, fmt) for ex in train_raw]
    eval_rows = [_format_example(ex, fmt) for ex in eval_raw]

    dataset_path = output_dir / "dataset.jsonl"
    train_path = output_dir / "train.jsonl"
    eval_path = output_dir / "eval.jsonl"
    raw_path = output_dir / "raw_examples.jsonl"
    protocol_path = output_dir / "protocol_examples.jsonl"
    quality_path = output_dir / "quality_report.json"
    sample_quality_path = output_dir / "sample_quality_report.json"
    sample_review_path = output_dir / "sample_review.json"
    evaluation_path = output_dir / "evaluation_report.json"
    governance_path = output_dir / "governance_report.json"
    evaluation_summary_path = output_dir / "evaluation_summary.json"
    plan_path = output_dir / "training_plan.json"
    report_path = output_dir / "report.md"

    _write_jsonl(raw_path, examples)
    _write_jsonl(protocol_path, [ex for ex in examples if str(ex.get("task_type", "")) == "action_protocol_sft"])
    _write_jsonl(dataset_path, [_format_example(ex, fmt) for ex in examples])
    _write_jsonl(train_path, train_rows)
    _write_jsonl(eval_path, eval_rows)

    evaluation_report = evaluate_training_dataset(
        examples,
        rejected,
        dataset_format=fmt,
        train_count=len(train_rows),
        eval_count=len(eval_rows),
    )
    evaluation = evaluation_report.to_dict()
    governance_report = evaluate_dataset_governance(examples)
    governance = governance_report.to_dict()
    sample_quality = sample_quality_report.to_dict()
    evaluation_summary = aggregate_metric_reports(
        [evaluation, governance, sample_quality],
        stage="training.prepare_summary",
    ).to_dict()
    quality = training_quality_summary(evaluation_report)
    plan = _training_plan(
        model_hint=inp.model_hint,
        dataset_format=fmt,
        train_path=train_path,
        eval_path=eval_path,
        train_count=len(train_rows),
        eval_count=len(eval_rows),
    )
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    sample_quality_path.write_text(json.dumps(sample_quality, ensure_ascii=False, indent=2), encoding="utf-8")
    sample_review_path.write_text(json.dumps(sample_decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    governance_path.write_text(json.dumps(governance, ensure_ascii=False, indent=2), encoding="utf-8")
    evaluation_summary_path.write_text(json.dumps(evaluation_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(
        "\n".join(
            [
                "# Fine-tuning Dataset Report",
                "",
                f"Format: `{fmt}`",
                f"Examples: {len(examples)}",
                f"Train: {len(train_rows)}",
                f"Eval: {len(eval_rows)}",
                f"Rejected: {sum(rejected.values())}",
                f"Sample quality: {sample_quality.get('overall_score')} ({sample_quality.get('grade')})",
                f"Evaluation: {evaluation.get('overall_score')} ({evaluation.get('grade')})",
                f"Governance: {governance.get('overall_score')} ({governance.get('grade')})",
                "",
                "## Next Steps",
                "",
                *[f"- {step}" for step in plan["recommended_next_steps"]],
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "raw_examples": str(raw_path),
        "protocol_examples": str(protocol_path),
        "dataset": str(dataset_path),
        "train": str(train_path),
        "eval": str(eval_path),
        "quality_report": str(quality_path),
        "sample_quality_report": str(sample_quality_path),
        "sample_review": str(sample_review_path),
        "evaluation_report": str(evaluation_path),
        "governance_report": str(governance_path),
        "evaluation_summary": str(evaluation_summary_path),
        "training_plan": str(plan_path),
        "report": str(report_path),
    }
    manifest = build_run_manifest(
        kind="training_prepare",
        input_summary={
            "learning_dirs": [str(path) for path in inp.learning_dirs],
            "solution_dirs": [str(path) for path in inp.solution_dirs],
            "dataset_format": fmt,
            "eval_ratio": inp.eval_ratio,
            "max_examples": inp.max_examples,
            "model_hint": inp.model_hint,
            "include_protocol_examples": bool(inp.include_protocol_examples),
            "protocol_example_limit": max(int(inp.protocol_example_limit), 0),
        },
        files=files,
        evaluation=evaluation_summary,
        artifacts=[str(dataset_path), str(train_path), str(eval_path)],
        source_refs=[{"type": "learning_dir", "path": str(path)} for path in inp.learning_dirs]
        + [{"type": "solution_dir", "path": str(path)} for path in inp.solution_dirs],
        risks=["manual_license_privacy_secret_review_required"],
    )
    manifest_path = write_run_manifest(output_dir, manifest)
    files["run_manifest"] = str(manifest_path)
    snapshot = create_dataset_snapshot(output_dir, shard_size=1024, write_shards=True)
    snapshot_path = output_dir / "dataset_snapshot_manifest.json"
    files["dataset_snapshot_manifest"] = str(snapshot_path)
    manifest["files"]["dataset_snapshot_manifest"] = str(snapshot_path)
    manifest["artifacts"].append(str(snapshot_path))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return TrainingPrepareResult(
        output_dir=str(output_dir),
        dataset_format=fmt,
        total_examples=len(examples),
        train_examples=len(train_rows),
        eval_examples=len(eval_rows),
        rejected_examples=sum(rejected.values()),
        files=files,
        quality=quality,
        plan=plan,
        sample_quality=sample_quality,
        evaluation=evaluation,
        governance=governance,
        evaluation_summary=evaluation_summary,
        manifest=manifest,
    )
