from __future__ import annotations

import json
from pathlib import Path

from agent.chains.training import TrainingPrepareInput, prepare_fine_tuning_dataset
from agent.training.protocol_examples import build_protocol_examples


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _make_learning_run(root: Path) -> Path:
    learning = root / "learning"
    _write_jsonl(
        learning / "training_examples.jsonl",
        [
            {
                "example_id": "ex-1",
                "task_type": "rag_grounded_answer",
                "instruction": "基于证据回答问题。",
                "input": "问题：hello route 在哪里",
                "output": "hello route 位于 app.py，并返回 ok。",
                "citations": [{"path": "app.py", "start_line": 1, "end_line": 5}],
                "metadata": {"repo": "local/demo"},
            },
            {
                "example_id": "bad",
                "task_type": "bad",
                "instruction": "短",
                "input": "",
                "output": "x",
            },
        ],
    )
    return learning


def _make_solution_run(root: Path) -> Path:
    run = root / "run_demo"
    (run / "docs").mkdir(parents=True)
    (run / "solution_manifest.json").write_text(
        json.dumps(
            {
                "schema": "solution_manifest.v1",
                "template": "spring-vue-management",
                "stack": "Spring Boot + Vue",
                "goal": "员工管理系统",
                "retrieval_tags": ["crud", "approval"],
                "artifact_hints": ["README.md"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run / "docs" / "SOLUTION_BACKUP.md").write_text(
        "这是一个可复用的员工管理系统方案，包含 README、API 契约、数据库设计和静态预览。",
        encoding="utf-8",
    )
    return run


def test_prepare_fine_tuning_dataset_from_learning_and_solutions(tmp_path: Path) -> None:
    learning = _make_learning_run(tmp_path)
    _make_solution_run(tmp_path)
    out_dir = tmp_path / "training_out"

    result = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=out_dir,
            learning_dirs=(learning,),
            solution_dirs=(tmp_path,),
            dataset_format="messages",
            eval_ratio=0.5,
            min_chars=10,
            model_hint="deepseek-coder",
            include_protocol_examples=False,
        )
    )

    assert result.total_examples == 2
    assert result.train_examples == 1
    assert result.eval_examples == 1
    assert result.rejected_examples == 1
    assert Path(result.files["train"]).exists()
    assert Path(result.files["eval"]).exists()
    assert result.quality["citation_rate"] == 1.0
    assert result.sample_quality["stage"] == "training.sample_quality"
    assert result.evaluation["stage"] == "training.dataset_prepare"
    assert result.governance["stage"] == "training.dataset_governance"
    assert result.evaluation_summary["stage"] == "training.prepare_summary"
    assert Path(result.files["evaluation_report"]).exists()
    assert Path(result.files["governance_report"]).exists()
    assert Path(result.files["sample_quality_report"]).exists()
    assert Path(result.files["sample_review"]).exists()
    assert Path(result.files["run_manifest"]).exists()
    assert Path(result.files["dataset_snapshot_manifest"]).exists()
    assert result.plan["status"] == "prepared_not_started"
    assert "DeepSeek-Coder" in result.plan["base_model"]

    first = json.loads(Path(result.files["dataset"]).read_text(encoding="utf-8").splitlines()[0])
    assert "messages" in first
    assert first["messages"][0]["role"] == "system"
    snapshot = json.loads(Path(result.files["dataset_snapshot_manifest"]).read_text(encoding="utf-8"))
    assert snapshot["schema"] == "dataset_snapshot_manifest.v1"
    assert snapshot["source_manifest_id"] == result.manifest["manifest_id"]


def test_prepare_fine_tuning_dataset_can_export_alpaca(tmp_path: Path) -> None:
    learning = _make_learning_run(tmp_path)
    out_dir = tmp_path / "training_alpaca"

    result = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=out_dir,
            learning_dirs=(learning,),
            dataset_format="alpaca",
            eval_ratio=0.0,
            min_chars=10,
            include_protocol_examples=False,
        )
    )

    row = json.loads(Path(result.files["dataset"]).read_text(encoding="utf-8").splitlines()[0])
    assert set(["instruction", "input", "output"]).issubset(row)
    assert result.eval_examples == 0


def test_prepare_fine_tuning_dataset_respects_learning_promotion_manifest(tmp_path: Path) -> None:
    learning = tmp_path / "learning_gated"
    _write_jsonl(
        learning / "training_examples.jsonl",
        [
            {
                "example_id": "good",
                "task_type": "knowledge_card_qa",
                "instruction": "根据知识卡回答问题。",
                "input": "问题：如何运行",
                "output": "运行 python app.py，并访问 /hello。",
                "citations": [{"path": "README.md"}],
                "metadata": {"repo": "local/good_repo"},
            },
            {
                "example_id": "rejected",
                "task_type": "knowledge_card_qa",
                "instruction": "根据知识卡回答问题。",
                "input": "问题：如何运行",
                "output": "未知。",
                "citations": [{"path": "README.md"}],
                "metadata": {"repo": "local/bad_repo"},
            },
        ],
    )
    (learning / "knowledge_promotion.json").write_text(
        json.dumps(
            {
                "schema": "knowledge_promotion.v1",
                "summary": {"repos": 2, "promoted": 1, "rejected": 1},
                "promoted": [{"repo": "local/good_repo", "eligible": True}],
                "rejected": [{"repo": "local/bad_repo", "eligible": False}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=tmp_path / "training_from_gate",
            learning_dirs=(learning,),
            eval_ratio=0.0,
            min_chars=4,
            include_protocol_examples=False,
        )
    )

    rows = [
        json.loads(line)
        for line in Path(result.files["raw_examples"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert result.total_examples == 1
    assert rows[0]["metadata"]["repo"] == "local/good_repo"
    assert rows[0]["metadata"]["knowledge_gate"]["schema"] == "knowledge_promotion.v1"


def test_prepare_fine_tuning_dataset_includes_protocol_slice_by_default(tmp_path: Path) -> None:
    learning = _make_learning_run(tmp_path)

    result = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=tmp_path / "training_with_protocol",
            learning_dirs=(learning,),
            eval_ratio=0.0,
            min_chars=10,
        )
    )

    protocol_rows = [
        json.loads(line)
        for line in Path(result.files["protocol_examples"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(protocol_rows) == len(build_protocol_examples())
    assert result.evaluation["summary"]["protocol_examples"] == len(build_protocol_examples())
    assert result.evaluation["metrics"]["protocol_validity_rate"]["value"] == 1.0
    assert protocol_rows[0]["task_type"] == "action_protocol_sft"


def test_prepare_fine_tuning_dataset_keeps_protocol_examples_in_eval_split(tmp_path: Path) -> None:
    learning = _make_learning_run(tmp_path)

    result = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=tmp_path / "training_with_protocol_eval",
            learning_dirs=(learning,),
            eval_ratio=0.2,
            min_chars=10,
        )
    )

    eval_rows = [
        json.loads(line)
        for line in Path(result.files["eval"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row["metadata"]["task_type"] == "action_protocol_sft" for row in eval_rows)
