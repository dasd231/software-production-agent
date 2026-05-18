from __future__ import annotations

from agent.evaluation.crawler import evaluate_repo_profile, repo_quality_summary
from agent.evaluation.aggregate import aggregate_metric_reports
from agent.evaluation.governance import evaluate_dataset_governance
from agent.evaluation.knowledge import decide_knowledge_promotion, evaluate_knowledge_asset
from agent.evaluation.card_quality import review_cards
from agent.evaluation.rag import evaluate_unified_rag
from agent.evaluation.research import evaluate_research_synthesis
from agent.evaluation.sample_quality import review_training_examples
from agent.evaluation.slice_quality import review_slices
from agent.evaluation.training import evaluate_training_dataset, training_quality_summary
from agent.evidence.arbiter import arbitrate_evidence
from agent.learning.schemas import (
    CodeSlice,
    KnowledgeCard,
    ParsedReadme,
    RepoCandidate,
    RepoLearningArtifact,
    SandboxReport,
    StructureSummary,
)


def test_crawler_evaluation_scores_fullstack_profile() -> None:
    candidate = RepoCandidate(full_name="demo/fullstack", html_url="https://example.test", stargazers_count=150, license_spdx="MIT")
    structure = StructureSummary(
        files=["README.md", ".github/workflows/ci.yml", "package.json", "src/App.vue", "src/main.py", "tests/test_app.py"],
        directories=["src", "tests"],
        languages={"py": 1, "vue": 1},
        entrypoints=["src/main.py"],
        tests=["tests/test_app.py"],
        package_files=["package.json"],
    )
    arch = {"shape": "fullstack", "tags": ["frontend-backend"]}

    report = evaluate_repo_profile(candidate, structure, arch, "Demo docs")
    quality = repo_quality_summary(report)

    assert report.to_dict()["stage"] == "crawler.repo_profile"
    assert quality["score"] >= 8.0
    assert "frontend_backend_pair" in quality["reasons"]
    assert "tests" in quality["reasons"]


def test_training_evaluation_keeps_legacy_quality_summary_shape() -> None:
    examples = [
        {
            "task_type": "rag_grounded_answer",
            "instruction": "基于证据回答问题。",
            "output": "hello route 位于 app.py，并返回 ok。",
            "citations": [{"path": "app.py"}],
        },
        {
            "task_type": "solution_reuse_sft",
            "instruction": "根据历史方案输出复用方案。",
            "output": "复用 README、API 契约、数据库设计和静态预览。",
            "citations": [{"path": "solution_manifest.json"}],
        },
    ]

    report = evaluate_training_dataset(examples, {"short_output": 1}, dataset_format="messages", train_count=1, eval_count=1)
    quality = training_quality_summary(report)

    assert report.to_dict()["metrics"]["citation_rate"]["value"] == 1.0
    assert quality["with_citations"] == 2
    assert quality["rejected"]["short_output"] == 1
    assert quality["evaluation_score"] == report.overall_score


def test_training_evaluation_flags_extreme_task_imbalance() -> None:
    balanced_edge = evaluate_training_dataset(
        [
            {
                "task_type": "knowledge_card_qa",
                "instruction": "根据知识卡回答问题",
                "output": "x" * 30,
                "citations": [{"path": "README.md"}],
            }
            for _ in range(19)
        ]
        + [
            {
                "task_type": "rag_grounded_answer",
                "instruction": "基于证据回答问题",
                "output": "y" * 30,
                "citations": [{"path": "README.md"}],
            }
        ],
        {},
        dataset_format="messages",
        train_count=18,
        eval_count=2,
    )
    imbalanced = evaluate_training_dataset(
        [
            {
                "task_type": "knowledge_card_qa",
                "instruction": "根据知识卡回答问题",
                "output": "x" * 30,
                "citations": [{"path": "README.md"}],
            }
            for _ in range(99)
        ]
        + [
            {
                "task_type": "rag_grounded_answer",
                "instruction": "基于证据回答问题",
                "output": "y" * 30,
                "citations": [{"path": "README.md"}],
            }
        ],
        {},
        dataset_format="messages",
        train_count=90,
        eval_count=10,
    )

    assert balanced_edge.metric("min_task_share").value == 0.05
    assert balanced_edge.metric("min_task_share").status == "ok"
    assert imbalanced.metric("min_task_share").value == 0.01
    assert imbalanced.metric("min_task_share").status == "watch"


def test_research_evaluation_tracks_source_coverage() -> None:
    answer = "优先复用 [S1]，再结合 [R1]，最新变化参考 [W1]。"

    report = evaluate_research_synthesis(
        query="employee approval",
        answer=answer,
        solution_hits=[{"run_id": "s1"}],
        rag_hints=[{"path": "app.py"}],
        web_results=[{"url": "https://example.test"}],
        trace={"web_enabled": True, "llm_ok": False},
    )
    data = report.to_dict()

    assert data["metrics"]["citation_label_coverage"]["score"] == 10.0
    assert data["summary"]["labels_missing"] == []
    assert data["overall_score"] >= 8.0


def test_rag_evaluation_reports_learning_store_health() -> None:
    summary = {
        "local": {"enabled": True, "hits": 1, "elapsed_ms": 20},
        "learning": {"enabled": True, "hits": 1, "elapsed_ms": 30, "stores": [{"ok": True}]},
        "total_hits": 2,
        "sources": {"local_workspace": 1, "learning_run": 1},
    }
    hints = [{"source": "local_workspace"}, {"source": "learning_run", "confidence": 0.8}]

    report = evaluate_unified_rag(summary, hints).to_dict()

    assert report["metrics"]["learning_store_health"]["score"] == 10.0
    assert report["metrics"]["total_hits"]["value"] == 2
    assert report["overall_score"] >= 8.0


def test_dataset_governance_blocks_secret_like_values() -> None:
    report = evaluate_dataset_governance(
        [
            {
                "instruction": "保存配置",
                "input": "",
                "output": "api_key='sk_test_secret_value'",
                "citations": [{"path": "README.md"}],
            }
        ]
    ).to_dict()

    assert report["metrics"]["secret_scan"]["status"] == "blocked"
    assert report["overall_score"] < 8.0


def test_knowledge_asset_evaluation_promotes_traceable_repo() -> None:
    artifact = RepoLearningArtifact(
        repo=RepoCandidate(full_name="demo/quality", html_url="https://example.test"),
        workspace="/tmp/quality",
        readme=ParsedReadme(
            path="README.md",
            title="Quality Repo",
            summary="A documented project.",
            sections={"install": "pip install demo", "usage": "python app.py", "testing": "pytest"},
        ),
        structure=StructureSummary(
            files=["README.md", "app.py", "tests/test_app.py", "requirements.txt"],
            directories=["tests"],
            languages={"python": 2, "markdown": 1},
            entrypoints=["app.py"],
            tests=["tests/test_app.py"],
            package_files=["requirements.txt"],
        ),
        slices=[
            CodeSlice(path="app.py", language="python", start_line=1, end_line=10, text="print('ok')"),
            CodeSlice(path="tests/test_app.py", language="python", start_line=1, end_line=4, text="def test_ok(): pass"),
            CodeSlice(path="README.md", language="markdown", start_line=1, end_line=8, text="# Quality Repo"),
        ],
        cards=[
            KnowledgeCard("overview", "summary", ["overview"], ["README.md"], ["what"]),
            KnowledgeCard("architecture", "summary", ["architecture"], ["app.py"], ["where"]),
        ],
        sandbox=SandboxReport(ok=True, checks=[{"name": "python_compile", "ok": True}]),
    )

    report = evaluate_knowledge_asset(artifact)
    decision = decide_knowledge_promotion(artifact, report)

    assert report.to_dict()["stage"] == "learning.knowledge_asset"
    assert report.to_dict()["metrics"]["card_traceability_rate"]["value"] == 1.0
    assert decision["eligible"] is True
    assert decision["decision"] == "promoted"


def test_slice_and_card_reviews_filter_duplicates_and_invalid_sources() -> None:
    slices = [
        CodeSlice(path="app.py", language="python", start_line=1, end_line=2, text="def hello():\n    return 'ok'", tokens=("hello", "return")),
        CodeSlice(path="app.py", language="python", start_line=1, end_line=2, text="def hello():\n    return 'ok'", tokens=("hello", "return")),
    ]
    cards = [
        KnowledgeCard("overview", "这是一个带有效来源的知识卡，用于测试质量审查。", ["overview"], ["README.md"], ["是什么"]),
        KnowledgeCard("bad", "无效来源卡片。", ["overview"], ["missing.md"], ["是什么"]),
    ]

    accepted_slices, _, slice_report = review_slices(slices)
    accepted_cards, _, card_report = review_cards(cards, known_paths={"README.md", "app.py"})

    assert len(accepted_slices) == 1
    assert slice_report.to_dict()["metrics"]["duplicate_rate"]["value"] == 0.5
    assert len(accepted_cards) == 1
    assert card_report.to_dict()["metrics"]["citation_validity_rate"]["value"] == 0.5


def test_sample_review_requires_citations_for_grounded_tasks() -> None:
    accepted, rejected, _, report = review_training_examples(
        [
            {
                "example_id": "good",
                "task_type": "rag_grounded_answer",
                "instruction": "基于证据回答问题。",
                "input": "问题",
                "output": "答案来自 README。",
                "citations": [{"path": "README.md"}],
            },
            {
                "example_id": "bad",
                "task_type": "rag_grounded_answer",
                "instruction": "基于证据回答问题。",
                "input": "问题",
                "output": "答案来自 README。",
                "citations": [],
            },
        ],
        min_chars=4,
        max_examples=10,
    )

    assert len(accepted) == 1
    assert rejected["missing_required_citations"] == 1
    assert report.to_dict()["stage"] == "training.sample_quality"


def test_sample_review_rejects_non_strict_action_protocol_rows() -> None:
    accepted, rejected, _, _ = review_training_examples(
        [
            {
                "example_id": "good",
                "task_type": "action_protocol_sft",
                "instruction": "只输出动作。",
                "input": "查看工作区",
                "output": '{"type":"action","action":"workspace_index","args":{}}',
                "citations": [{"path": "agent/core/protocol.py"}],
            },
            {
                "example_id": "bad",
                "task_type": "action_protocol_sft",
                "instruction": "只输出动作。",
                "input": "查看工作区",
                "output": '当然可以：{"type":"action","action":"workspace_index","args":{}}',
                "citations": [{"path": "agent/core/protocol.py"}],
            },
        ],
        min_chars=4,
        max_examples=10,
    )

    assert len(accepted) == 1
    assert rejected["invalid_action_protocol"] == 1


def test_aggregate_metric_reports_combines_stages() -> None:
    first = evaluate_dataset_governance([]).to_dict()
    second = evaluate_unified_rag({"local": {"hits": 1}, "learning": {}, "total_hits": 1, "sources": {"local": 1}}, [{"path": "a.py"}]).to_dict()

    summary = aggregate_metric_reports([first, second]).to_dict()

    assert summary["stage"] == "run.aggregate"
    assert summary["metrics"]["report_count"]["value"] == 2


def test_evidence_arbiter_prefers_local_sources() -> None:
    out = arbitrate_evidence(
        solution_hits=[{"stack": "Vue 3.5"}],
        rag_hints=[{"preview": "local project"}],
        web_results=[{"title": "Vue 3.6 released", "snippet": "version 3.6"}],
    )

    assert out["decision"] == "web_supplemental"
    assert out["source_order"][0] == "solution_library"
    assert out["conflicts"]
    assert out["conflict_details"][0]["left_source"] == "local_evidence"
    assert out["source_confidence"]["solution_library"]["basis"] == "accepted_or_curated_local_asset"
    assert out["decision_rationale"]
