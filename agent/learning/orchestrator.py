"""Agent learning pipeline orchestrator.

函数流程图：
    run_learning_pipeline(config)
      -> output_dir/repos 创建
      -> candidates:
           local_repos -> _candidate_from_local_repo()
           enable_github_network -> GitHubSearchClient.search()
      -> filter_repositories()
      -> for candidate:
           download_repo()
           parse_readme()
           parse_structure()
           slice_repository()
           build_knowledge_cards()
           run_sandbox_tests()
      -> build_vector_index(all_slices)
      -> build_training_examples()
      -> optional search_web()
      -> save vector_index.jsonl / cards.json / training_examples.jsonl / result.json / report.md
      -> LearningPipelineResult

你可以继续练算法/工程化的点：
    1. DAG 化：现在是顺序串联；可把 12 步变成可恢复 DAG 节点。
    2. 缓存：repo 下载、README 解析、切片、向量化都可以按 hash 缓存。
    3. 训练数据：可从 card + slice + RAG answer 导出 SFT/DPO/检索评测集。
    4. 质量回路：沙箱结果、RAG 命中率和用户反馈可反向更新 repo 评分。
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from agent.evaluation.aggregate import aggregate_metric_reports
from agent.evaluation.card_quality import review_cards
from agent.evaluation.knowledge import (
    KnowledgePromotionPolicy,
    decide_knowledge_promotion,
    evaluate_knowledge_asset,
)
from agent.evaluation.slice_quality import review_slices
from agent.learning.code_slicer import slice_repository
from agent.learning.filters import filter_repositories
from agent.learning.github_search import GitHubSearchClient
from agent.learning.hierarchical_rag import build_hierarchical_vector_index, save_hierarchy_artifacts
from agent.learning.knowledge_cards import build_knowledge_cards
from agent.learning.readme_parser import parse_readme
from agent.learning.repo_downloader import download_repo
from agent.learning.rag_pipeline import benchmark_research_config
from agent.learning.rag_qa import answer_question
from agent.learning.sandbox import run_sandbox_tests
from agent.learning.schemas import (
    LearningPipelineConfig,
    LearningPipelineResult,
    RepoCandidate,
    RepoLearningArtifact,
)
from agent.learning.structure_parser import parse_structure
from agent.learning.training_export import build_training_examples, save_training_examples_jsonl
from agent.learning.vector_store import VectorIndex
from agent.learning.web_search import search_web


def _candidate_from_local_repo(path: Path) -> RepoCandidate:
    path = path.resolve()
    return RepoCandidate(
        full_name=f"local/{path.name}",
        html_url=f"file://{path}",
        description="Local repository supplied to learning pipeline.",
        stargazers_count=0,
        license_spdx="LOCAL",
        updated_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        local_path=str(path),
    )


def _save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_report(
    path: Path,
    *,
    config: LearningPipelineConfig,
    artifacts: list[RepoLearningArtifact],
    promoted_artifacts: list[RepoLearningArtifact],
    vector_index: VectorIndex,
    sample_answer: dict[str, object],
    training_examples_count: int,
    quality_summary: dict[str, object],
) -> None:
    lines = [
        "# Learning Pipeline Report",
        "",
        f"Query: `{config.query}`",
        "",
        f"Repos processed: {len(artifacts)}",
        f"Repos promoted: {len(promoted_artifacts)}",
        f"Repos rejected: {len(artifacts) - len(promoted_artifacts)}",
        f"Knowledge quality: {quality_summary.get('overall_score', 0.0)} ({quality_summary.get('grade', 'n/a')})",
        f"Vector records: {len(vector_index.records)}",
        f"Parent chunks: {len(getattr(vector_index, 'parent_chunks', {}) or {})}",
        f"RAG hierarchy: child retrieval -> parent context, parent_lines={config.rag_hierarchy_parent_lines}, overlap={config.rag_hierarchy_parent_overlap_lines}",
        f"Training examples: {training_examples_count}",
        "",
        "## Repositories",
        "",
    ]
    for artifact in artifacts:
        lines.extend(
            [
                f"### {artifact.repo.full_name}",
                "",
                f"- Workspace: `{artifact.workspace}`",
                f"- README: `{artifact.readme.path}`",
                f"- Files: {len(artifact.structure.files)}",
                f"- Languages: `{artifact.structure.languages}`",
                f"- Slices: {len(artifact.slices)}",
                f"- Cards: {len(artifact.cards)}",
                f"- Sandbox: `{artifact.sandbox.ok if artifact.sandbox else 'skipped'}`",
                f"- Quality: `{artifact.quality.get('overall_score', 'n/a')}` ({artifact.quality.get('grade', 'n/a')})",
                f"- Promotion: `{artifact.promotion.get('decision', 'n/a')}`",
                f"- Promotion reasons: `{artifact.promotion.get('reasons', [])}`",
                "",
            ]
        )
    lines.extend(["## Sample RAG Answer", "", str(sample_answer.get("answer", "")), ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run_learning_pipeline(config: LearningPipelineConfig) -> LearningPipelineResult:
    output_dir = config.output_dir.resolve()
    repos_dir = output_dir / "repos"
    output_dir.mkdir(parents=True, exist_ok=True)
    repos_dir.mkdir(parents=True, exist_ok=True)

    candidates = [_candidate_from_local_repo(path) for path in config.local_repos]
    if config.enable_github_network and config.query.strip():
        candidates.extend(GitHubSearchClient().search(config.query, per_page=max(config.repo_limit * 3, 5)))
    candidates = filter_repositories(
        candidates,
        min_stars=config.min_stars,
        allowed_licenses=config.allowed_licenses,
        updated_after=config.updated_after,
        max_count=config.repo_limit,
    )

    artifacts: list[RepoLearningArtifact] = []
    slice_reviews: list[dict[str, object]] = []
    card_reviews: list[dict[str, object]] = []
    for candidate in candidates:
        workspace = download_repo(candidate, repos_dir)
        readme = parse_readme(workspace)
        structure = parse_structure(workspace)
        raw_slices = slice_repository(workspace)
        raw_cards = build_knowledge_cards(candidate, readme, structure, raw_slices)
        slices, slice_decisions, slice_report = review_slices(raw_slices)
        cards, card_decisions, card_report = review_cards(raw_cards, known_paths=set(structure.files))
        sandbox = run_sandbox_tests(workspace) if config.enable_sandbox else None
        slice_reviews.append(
            {
                "repo": candidate.full_name,
                "report": slice_report.to_dict(),
                "decisions": slice_decisions,
            }
        )
        card_reviews.append(
            {
                "repo": candidate.full_name,
                "report": card_report.to_dict(),
                "decisions": card_decisions,
            }
        )
        artifacts.append(
            RepoLearningArtifact(
                repo=candidate,
                workspace=str(workspace),
                readme=readme,
                structure=structure,
                slices=slices,
                cards=cards,
                sandbox=sandbox,
            )
        )

    promotion_policy = KnowledgePromotionPolicy()
    quality_reports: list[dict[str, object]] = []
    gated_artifacts: list[RepoLearningArtifact] = []
    for artifact in artifacts:
        report = evaluate_knowledge_asset(artifact)
        quality = report.to_dict()
        promotion = decide_knowledge_promotion(artifact, report, policy=promotion_policy)
        quality_reports.append(quality)
        gated_artifacts.append(replace(artifact, quality=quality, promotion=promotion))
    artifacts = gated_artifacts
    promoted_artifacts = [artifact for artifact in artifacts if bool(artifact.promotion.get("eligible"))]

    quality_summary = aggregate_metric_reports(
        quality_reports,
        stage="learning.knowledge_quality_summary",
    ).to_dict()
    quality_payload = {
        "schema": "knowledge_quality_run.v1",
        "summary": {
            "repos": len(artifacts),
            "promoted": len(promoted_artifacts),
            "rejected": len(artifacts) - len(promoted_artifacts),
        },
        "aggregate": quality_summary,
        "reports": quality_reports,
    }
    promotion_payload = {
        "schema": "knowledge_promotion.v1",
        "policy": promotion_policy.to_dict(),
        "summary": {
            "repos": len(artifacts),
            "promoted": len(promoted_artifacts),
            "rejected": len(artifacts) - len(promoted_artifacts),
        },
        "promoted": [artifact.promotion for artifact in promoted_artifacts],
        "rejected": [artifact.promotion for artifact in artifacts if not bool(artifact.promotion.get("eligible"))],
    }
    quality_report_path = output_dir / "knowledge_quality_report.json"
    promotion_report_path = output_dir / "knowledge_promotion.json"
    slice_quality_path = output_dir / "slice_quality_report.json"
    card_quality_path = output_dir / "card_quality_report.json"
    quality_funnel_path = output_dir / "quality_funnel.json"
    _save_json(quality_report_path, quality_payload)
    _save_json(promotion_report_path, promotion_payload)
    _save_json(
        slice_quality_path,
        {
            "schema": "slice_quality_run.v1",
            "aggregate": aggregate_metric_reports(
                [row["report"] for row in slice_reviews if isinstance(row.get("report"), dict)],
                stage="learning.slice_quality_summary",
            ).to_dict(),
            "reviews": slice_reviews,
        },
    )
    _save_json(
        card_quality_path,
        {
            "schema": "card_quality_run.v1",
            "aggregate": aggregate_metric_reports(
                [row["report"] for row in card_reviews if isinstance(row.get("report"), dict)],
                stage="learning.card_quality_summary",
            ).to_dict(),
            "reviews": card_reviews,
        },
    )
    _save_json(
        quality_funnel_path,
        {
            "schema": "knowledge_quality_funnel.v1",
            "repos": {
                "raw": len(artifacts),
                "promoted": len(promoted_artifacts),
                "rejected": len(artifacts) - len(promoted_artifacts),
            },
            "slices": {
                "raw": sum(int(row["report"]["summary"]["slices"]) for row in slice_reviews),
                "accepted": sum(int(row["report"]["summary"]["accepted"]) for row in slice_reviews),
                "rejected": sum(int(row["report"]["summary"]["rejected"]) for row in slice_reviews),
            },
            "cards": {
                "raw": sum(int(row["report"]["summary"]["cards"]) for row in card_reviews),
                "accepted": sum(int(row["report"]["summary"]["accepted"]) for row in card_reviews),
                "rejected": sum(int(row["report"]["summary"]["rejected"]) for row in card_reviews),
            },
        },
    )

    promoted_slices = [sl for artifact in promoted_artifacts for sl in artifact.slices]
    vector_index, parent_chunks, hierarchy_meta = build_hierarchical_vector_index(
        promoted_slices,
        repo_id="learning_run",
        parent_max_lines=config.rag_hierarchy_parent_lines,
        parent_overlap_lines=config.rag_hierarchy_parent_overlap_lines,
        dimensions=config.vector_dimensions,
        use_openai=config.vector_use_openai,
        client=None,
        model=config.vector_openai_model,
        use_sentence_transformer=config.vector_use_sentence_transformer and not config.vector_use_openai,
        sentence_transformer_model=config.vector_sentence_transformer_model,
        st_batch_size=config.vector_st_batch_size,
        use_faiss=config.vector_use_faiss,
        use_faiss_hnsw=config.vector_faiss_hnsw,
        faiss_hnsw_min_vectors=config.vector_faiss_hnsw_min_vectors,
    )
    out_vec = output_dir / "vector_index.jsonl"
    vector_index.save_jsonl(out_vec)
    save_hierarchy_artifacts(output_dir, parent_chunks, hierarchy_meta)
    meta = vector_index.to_meta_dict()
    meta["st_batch_size"] = int(config.vector_st_batch_size)
    meta["hierarchical_rag"] = hierarchy_meta
    _save_json(output_dir / "vector_meta.json", meta)
    all_cards = [card for artifact in promoted_artifacts for card in artifact.cards]
    _save_json(output_dir / "knowledge_cards.json", [card.to_dict() for card in all_cards])
    web_results = search_web(config.query, top_k=5) if config.enable_web_search else []
    _save_json(output_dir / "web_results.json", [item.to_dict() for item in web_results])
    rag_model = config.rag_llm_model.strip() or None
    web_ctx = [w.to_dict() for w in web_results] if web_results else None
    research = benchmark_research_config() if config.rag_research else None
    use_bm25 = config.rag_use_bm25 or bool(config.rag_research)
    sample_answer = (
        answer_question(
            config.query,
            vector_index,
            all_cards,
            use_bm25=use_bm25,
            use_generative=config.rag_use_generative,
            llm_provider=config.rag_llm_provider,
            llm_model=rag_model,
            web_results=web_ctx,
            research=research,
            parent_chunks=parent_chunks,
        )
        if config.query
        else {}
    )
    training_examples = build_training_examples(
        promoted_artifacts,
        vector_index,
        query=config.query,
        rag_queries=config.rag_training_queries,
        rag_query_limit=max(int(config.rag_training_query_limit), 0),
    )
    save_training_examples_jsonl(output_dir / "training_examples.jsonl", training_examples)
    report_path = output_dir / "report.md"
    _write_report(
        report_path,
        config=config,
        artifacts=artifacts,
        promoted_artifacts=promoted_artifacts,
        vector_index=vector_index,
        sample_answer=sample_answer,
        training_examples_count=len(training_examples),
        quality_summary=quality_summary,
    )
    result = LearningPipelineResult(
        query=config.query,
        output_dir=str(output_dir),
        repos=artifacts,
        web_results=web_results,
        vector_records=len(vector_index.records),
        training_examples=len(training_examples),
        report_path=str(report_path),
        promoted_repos=len(promoted_artifacts),
        rejected_repos=len(artifacts) - len(promoted_artifacts),
        quality_report_path=str(quality_report_path),
        promotion_report_path=str(promotion_report_path),
    )
    _save_json(output_dir / "result.json", result.to_dict())
    return result
