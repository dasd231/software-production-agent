"""Canonical catalog for internet-scale repository-model training."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProjectCorpusSourceSpec:
    id: str
    label: str
    tier: str
    modalities: tuple[str, ...]
    evidence_role: str
    acquisition_mode: str
    license_policy: str
    refresh_cadence: str
    sampling_weight: float
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "project_corpus_source.v1",
            "id": self.id,
            "label": self.label,
            "tier": self.tier,
            "modalities": list(self.modalities),
            "evidence_role": self.evidence_role,
            "acquisition_mode": self.acquisition_mode,
            "license_policy": self.license_policy,
            "refresh_cadence": self.refresh_cadence,
            "sampling_weight": self.sampling_weight,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ProjectTrainingTaskSpec:
    id: str
    label: str
    capability: str
    supervision: str
    target_output: str
    primary_metrics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "project_training_task.v1",
            "id": self.id,
            "label": self.label,
            "capability": self.capability,
            "supervision": self.supervision,
            "target_output": self.target_output,
            "primary_metrics": list(self.primary_metrics),
        }


@dataclass(frozen=True)
class ProjectBenchmarkSpec:
    id: str
    label: str
    capability_slice: str
    public_reference: str
    primary_metrics: tuple[str, ...]
    stage_gate: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "project_benchmark.v1",
            "id": self.id,
            "label": self.label,
            "capability_slice": self.capability_slice,
            "public_reference": self.public_reference,
            "primary_metrics": list(self.primary_metrics),
            "stage_gate": self.stage_gate,
        }


@dataclass(frozen=True)
class ProjectTrainingStageSpec:
    id: str
    label: str
    kind: str
    objective: str
    source_ids: tuple[str, ...]
    task_mix: tuple[tuple[str, float], ...]
    exit_criteria: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "project_training_stage.v1",
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "objective": self.objective,
            "source_ids": list(self.source_ids),
            "task_mix": [
                {"task_id": task_id, "weight": weight}
                for task_id, weight in self.task_mix
            ],
            "exit_criteria": list(self.exit_criteria),
        }


_CORPUS_SOURCES: tuple[ProjectCorpusSourceSpec, ...] = (
    ProjectCorpusSourceSpec(
        id="open_repo_snapshots",
        label="Open repository snapshots",
        tier="foundation",
        modalities=("source_code", "tree", "manifests"),
        evidence_role="base repository corpus",
        acquisition_mode="archive_snapshot",
        license_policy="allowlist_or_permissive_only",
        refresh_cadence="quarterly",
        sampling_weight=0.34,
        notes=(
            "Prefer large archived snapshots before live crawling.",
            "Keep repository identity, commit hash and license attached to every shard.",
        ),
    ),
    ProjectCorpusSourceSpec(
        id="repository_docs",
        label="Repository docs and ADRs",
        tier="semantic",
        modalities=("readme", "docs", "adr", "design_notes"),
        evidence_role="architecture semantics",
        acquisition_mode="repo_sidecar",
        license_policy="inherit_repo_license",
        refresh_cadence="with_repo_snapshot",
        sampling_weight=0.16,
        notes=(
            "Treat docs as first-class project knowledge rather than decorative text.",
            "Preserve path-level grounding for later citation tasks.",
        ),
    ),
    ProjectCorpusSourceSpec(
        id="dependency_manifests",
        label="Dependency and build manifests",
        tier="structural",
        modalities=("package_manifest", "lockfile", "build_config"),
        evidence_role="dependency graph",
        acquisition_mode="repo_sidecar",
        license_policy="inherit_repo_license",
        refresh_cadence="with_repo_snapshot",
        sampling_weight=0.10,
        notes=("Needed for package graph, build-system and service-boundary reasoning.",),
    ),
    ProjectCorpusSourceSpec(
        id="development_traces",
        label="Issues, pull requests and commits",
        tier="evolution",
        modalities=("issues", "pull_requests", "commit_messages", "release_notes"),
        evidence_role="project evolution and rationale",
        acquisition_mode="forge_api",
        license_policy="source_platform_policy_plus_repo_gate",
        refresh_cadence="monthly",
        sampling_weight=0.14,
        notes=(
            "Use only after repository provenance and policy checks are retained.",
            "Links natural-language intent to concrete code changes.",
        ),
    ),
    ProjectCorpusSourceSpec(
        id="official_reference_docs",
        label="Official framework and package docs",
        tier="external_semantic",
        modalities=("api_docs", "guides", "specs"),
        evidence_role="library semantics",
        acquisition_mode="official_doc_snapshot",
        license_policy="source_specific_allowlist",
        refresh_cadence="monthly",
        sampling_weight=0.08,
        notes=("Used to disambiguate external symbols, not to replace repository evidence.",),
    ),
    ProjectCorpusSourceSpec(
        id="execution_signals",
        label="Tests, CI and examples",
        tier="behavioral",
        modalities=("tests", "ci_configs", "examples", "fixtures"),
        evidence_role="runtime behavior",
        acquisition_mode="repo_sidecar",
        license_policy="inherit_repo_license",
        refresh_cadence="with_repo_snapshot",
        sampling_weight=0.18,
        notes=("Essential for impact analysis and test-grounded reasoning.",),
    ),
)


_TRAINING_TASKS: tuple[ProjectTrainingTaskSpec, ...] = (
    ProjectTrainingTaskSpec(
        id="repo_structure_mapping",
        label="Repository structure mapping",
        capability="map modules, layers and service boundaries",
        supervision="self_supervised_plus_synthetic",
        target_output="structured project map",
        primary_metrics=("module_f1", "layer_accuracy"),
    ),
    ProjectTrainingTaskSpec(
        id="symbol_grounding",
        label="Symbol grounding",
        capability="resolve symbols to files and definitions",
        supervision="parser_derived",
        target_output="symbol -> definition evidence",
        primary_metrics=("symbol_recall_at_k", "definition_exact_match"),
    ),
    ProjectTrainingTaskSpec(
        id="cross_file_dependency",
        label="Cross-file dependency reasoning",
        capability="follow imports, calls and data flow across files",
        supervision="graph_derived",
        target_output="dependency edge/path prediction",
        primary_metrics=("edge_f1", "path_recall"),
    ),
    ProjectTrainingTaskSpec(
        id="evidence_retrieval",
        label="Repository evidence retrieval",
        capability="retrieve the few files and spans needed for a question",
        supervision="contrastive",
        target_output="ranked evidence spans",
        primary_metrics=("recall_at_5", "mrr"),
    ),
    ProjectTrainingTaskSpec(
        id="repo_grounded_qa",
        label="Repository-grounded QA",
        capability="answer repo questions with citations",
        supervision="human_or_synthetic_grounded_sft",
        target_output="answer plus cited evidence",
        primary_metrics=("answer_f1", "citation_precision"),
    ),
    ProjectTrainingTaskSpec(
        id="architecture_summary",
        label="Architecture summarization",
        capability="compress project intent, boundaries and data flow",
        supervision="distillation_plus_review",
        target_output="project memory card",
        primary_metrics=("coverage_score", "faithfulness_score"),
    ),
    ProjectTrainingTaskSpec(
        id="issue_to_code_localization",
        label="Issue-to-code localization",
        capability="link natural-language intent to likely files and symbols",
        supervision="development_trace_alignment",
        target_output="ranked files and rationale",
        primary_metrics=("file_recall_at_k", "localization_mrr"),
    ),
    ProjectTrainingTaskSpec(
        id="change_impact_reasoning",
        label="Change impact reasoning",
        capability="estimate affected modules and tests before editing",
        supervision="commit_diff_plus_test_graph",
        target_output="impact set with justification",
        primary_metrics=("impact_f1", "test_recall"),
    ),
    ProjectTrainingTaskSpec(
        id="cross_file_completion",
        label="Cross-file completion",
        capability="complete code using repository context",
        supervision="masked_code_modeling",
        target_output="repository-aware completion",
        primary_metrics=("exact_match", "edit_similarity"),
    ),
    ProjectTrainingTaskSpec(
        id="test_guided_fixing",
        label="Test-guided fixing",
        capability="use failing tests and project context to propose fixes",
        supervision="repair_trace_sft",
        target_output="patch plan or patch",
        primary_metrics=("test_pass_rate", "patch_acceptance"),
    ),
)


_BENCHMARKS: tuple[ProjectBenchmarkSpec, ...] = (
    ProjectBenchmarkSpec(
        id="coderepoqa",
        label="CodeRepoQA",
        capability_slice="repository QA",
        public_reference="CodeRepoQA",
        primary_metrics=("answer_accuracy", "evidence_grounding"),
        stage_gate="retrieval_grounded_understanding",
    ),
    ProjectBenchmarkSpec(
        id="coreqa",
        label="CoReQA",
        capability_slice="cross-file QA",
        public_reference="CoReQA",
        primary_metrics=("answer_f1", "retrieval_quality"),
        stage_gate="retrieval_grounded_understanding",
    ),
    ProjectBenchmarkSpec(
        id="longcodeu",
        label="LONGCODEU",
        capability_slice="long-context repository understanding",
        public_reference="LONGCODEU",
        primary_metrics=("task_accuracy", "long_context_robustness"),
        stage_gate="repo_representation_pretraining",
    ),
    ProjectBenchmarkSpec(
        id="repobench",
        label="RepoBench",
        capability_slice="repository-level completion",
        public_reference="RepoBench",
        primary_metrics=("exact_match", "edit_similarity"),
        stage_gate="repo_representation_pretraining",
    ),
    ProjectBenchmarkSpec(
        id="crosscodeeval",
        label="CrossCodeEval",
        capability_slice="cross-file code completion",
        public_reference="CrossCodeEval",
        primary_metrics=("exact_match", "retrieval_gain"),
        stage_gate="repo_representation_pretraining",
    ),
    ProjectBenchmarkSpec(
        id="internal_repo_holdout",
        label="Internal repository holdout",
        capability_slice="evidence retrieval and architecture QA",
        public_reference="internal",
        primary_metrics=("recall_at_5", "citation_precision", "latency_ms"),
        stage_gate="all",
    ),
)


_TRAINING_STAGES: tuple[ProjectTrainingStageSpec, ...] = (
    ProjectTrainingStageSpec(
        id="corpus_foundation",
        label="Corpus foundation",
        kind="data",
        objective="Build a provenance-preserving, de-duplicated repository corpus before any serious training.",
        source_ids=("open_repo_snapshots", "repository_docs", "dependency_manifests", "execution_signals"),
        task_mix=(),
        exit_criteria=(
            "license and provenance attached to every shard",
            "near-duplicate removal completed",
            "repository snapshots, docs, manifests and tests linked by repo_id",
        ),
    ),
    ProjectTrainingStageSpec(
        id="repo_representation_pretraining",
        label="Repository representation pretraining",
        kind="training",
        objective="Teach the model to encode project structure before asking it to answer project questions.",
        source_ids=("open_repo_snapshots", "repository_docs", "dependency_manifests", "execution_signals"),
        task_mix=(
            ("repo_structure_mapping", 0.22),
            ("symbol_grounding", 0.20),
            ("cross_file_dependency", 0.18),
            ("architecture_summary", 0.16),
            ("cross_file_completion", 0.24),
        ),
        exit_criteria=(
            "symbol grounding and cross-file dependency metrics clear stage floor",
            "long-context benchmarks stop regressing on held-out repos",
        ),
    ),
    ProjectTrainingStageSpec(
        id="retrieval_grounded_understanding",
        label="Retrieval-grounded understanding",
        kind="training",
        objective="Train a retriever-reader system that finds evidence first and answers second.",
        source_ids=("open_repo_snapshots", "repository_docs", "official_reference_docs", "execution_signals"),
        task_mix=(
            ("evidence_retrieval", 0.36),
            ("repo_grounded_qa", 0.28),
            ("issue_to_code_localization", 0.18),
            ("architecture_summary", 0.18),
        ),
        exit_criteria=(
            "retrieval recall@5 and citation precision clear promotion floor",
            "QA gains survive token-budget reduction tests",
        ),
    ),
    ProjectTrainingStageSpec(
        id="engineering_reasoning_alignment",
        label="Engineering reasoning alignment",
        kind="training",
        objective="Use project evolution traces to reason about intent, impact and repair.",
        source_ids=("development_traces", "execution_signals", "repository_docs", "open_repo_snapshots"),
        task_mix=(
            ("change_impact_reasoning", 0.24),
            ("test_guided_fixing", 0.22),
            ("issue_to_code_localization", 0.18),
            ("repo_grounded_qa", 0.18),
            ("cross_file_completion", 0.18),
        ),
        exit_criteria=(
            "issue localization and impact reasoning pass internal holdout",
            "repair quality improves without retrieval regressions",
        ),
    ),
)


def list_project_corpus_sources() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _CORPUS_SOURCES]


def list_project_training_tasks() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _TRAINING_TASKS]


def list_project_benchmarks() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _BENCHMARKS]


def list_project_training_stages() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _TRAINING_STAGES]
