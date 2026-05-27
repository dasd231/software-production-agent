from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ModelTarget = Literal["middle_model_rule_acceleration", "github_corpus_quality_evaluator"]


@dataclass(frozen=True)
class LocalTrainingExample:
    """One transparent CPU-training row with traceability metadata.

    The point of the local models is not raw model size; it is label hygiene.
    Every row keeps the source id and label source so a bad decision can be
    traced back to a workflow trace, repo ranking row, or human review.
    """

    example_id: str
    target: ModelTarget
    features: dict[str, float]
    label: int
    label_source: str = "heuristic"
    source_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LocalModelArtifact:
    schema: str
    target: ModelTarget
    model_type: str
    feature_names: tuple[str, ...]
    weights: dict[str, float]
    bias: float
    metrics: dict[str, Any]
    threshold: float = 0.5
    status: str = "trained"
    hard_gates: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["feature_names"] = list(self.feature_names)
        payload["hard_gates"] = list(self.hard_gates)
        payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class LocalPrediction:
    target: ModelTarget
    probability: float
    label: int
    threshold: float
    decision: str
    features: dict[str, float]
    hard_gate_triggered: bool = False
    hard_gate_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hard_gate_reasons"] = list(self.hard_gate_reasons)
        return payload


def resolve_artifact_path(path_or_dir: Path, filename: str) -> Path:
    """Accept either an artifact file or a training output directory."""

    path = Path(path_or_dir)
    if path.is_dir():
        return path / filename
    return path
