"""Shared schemas for the learning pipeline.

函数流程图：
    GitHub / Local repo / Web
      -> RepoCandidate
      -> ParsedReadme / StructureSummary
      -> CodeSlice
      -> VectorRecord
      -> KnowledgeCard
      -> TrainingExample
      -> SandboxReport
      -> LearningPipelineResult

你可以继续练算法/工程化的点：
    1. Schema 版本：现在是 dataclass；可加 schema_version 和迁移器。
    2. 质量指标：可以给每个对象加 confidence、source_hash、dedupe_key。
    3. 训练导出：可把 card/slice/answer 转成 instruction tuning 样本。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RepoCandidate:
    full_name: str
    html_url: str
    clone_url: str = ""
    description: str = ""
    stargazers_count: int = 0
    license_spdx: str = ""
    pushed_at: str = ""
    updated_at: str = ""
    default_branch: str = "main"
    topics: tuple[str, ...] = ()
    local_path: str = ""

    @property
    def name(self) -> str:
        return self.full_name.split("/")[-1] if self.full_name else ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["topics"] = list(self.topics)
        return out


@dataclass(frozen=True)
class ParsedReadme:
    path: str
    title: str
    summary: str
    sections: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StructureSummary:
    files: list[str]
    directories: list[str]
    languages: dict[str, int]
    entrypoints: list[str]
    tests: list[str]
    package_files: list[str]
    ignored_count: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeSlice:
    path: str
    language: str
    start_line: int
    end_line: int
    text: str
    tokens: tuple[str, ...] = ()

    @property
    def slice_id(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["tokens"] = list(self.tokens)
        return out


@dataclass(frozen=True)
class VectorRecord:
    record_id: str
    text: str
    metadata: dict[str, Any]
    vector: list[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeCard:
    title: str
    summary: str
    tags: list[str]
    source_paths: list[str]
    questions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainingExample:
    example_id: str
    task_type: str
    instruction: str
    input: str
    output: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "web"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SandboxReport:
    ok: bool
    checks: list[dict[str, Any]]
    commands_run: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearningPipelineConfig:
    query: str
    output_dir: Path
    local_repos: tuple[Path, ...] = ()
    repo_limit: int = 3
    min_stars: int = 0
    allowed_licenses: tuple[str, ...] = ()
    updated_after: str = ""
    enable_github_network: bool = False
    enable_web_search: bool = False
    enable_sandbox: bool = True
    vector_dimensions: int = 256
    vector_use_openai: bool = False
    vector_openai_model: str = "text-embedding-3-small"
    vector_use_faiss: bool = False
    vector_use_sentence_transformer: bool = False
    vector_sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_st_batch_size: int = 32
    vector_faiss_hnsw: bool = False
    vector_faiss_hnsw_min_vectors: int = 256
    rag_use_bm25: bool = False
    rag_use_generative: bool = False
    rag_llm_provider: str = "openai"
    rag_llm_model: str = ""
    rag_research: bool = False
    rag_training_queries: tuple[str, ...] = ()
    rag_training_query_limit: int = 1


@dataclass(frozen=True)
class RepoLearningArtifact:
    repo: RepoCandidate
    workspace: str
    readme: ParsedReadme
    structure: StructureSummary
    slices: list[CodeSlice]
    cards: list[KnowledgeCard]
    sandbox: SandboxReport | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    promotion: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo.to_dict(),
            "workspace": self.workspace,
            "readme": self.readme.to_dict(),
            "structure": self.structure.to_dict(),
            "slices": [x.to_dict() for x in self.slices],
            "cards": [x.to_dict() for x in self.cards],
            "sandbox": self.sandbox.to_dict() if self.sandbox else None,
            "quality": dict(self.quality),
            "promotion": dict(self.promotion),
        }


@dataclass(frozen=True)
class LearningPipelineResult:
    query: str
    output_dir: str
    repos: list[RepoLearningArtifact]
    web_results: list[SearchResult]
    vector_records: int
    training_examples: int
    report_path: str
    promoted_repos: int = 0
    rejected_repos: int = 0
    quality_report_path: str = ""
    promotion_report_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "output_dir": self.output_dir,
            "repos": [x.to_dict() for x in self.repos],
            "web_results": [x.to_dict() for x in self.web_results],
            "vector_records": self.vector_records,
            "training_examples": self.training_examples,
            "report_path": self.report_path,
            "promoted_repos": self.promoted_repos,
            "rejected_repos": self.rejected_repos,
            "quality_report_path": self.quality_report_path,
            "promotion_report_path": self.promotion_report_path,
        }
