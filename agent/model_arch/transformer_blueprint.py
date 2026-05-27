from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BlockOrder = Literal["attention_then_ffn", "ffn_then_attention_experiment"]


@dataclass(frozen=True, slots=True)
class TransformerStageSpec:
    name: str
    operation: str
    residual: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        return data


@dataclass(frozen=True, slots=True)
class AttentionFFNResidualSpec:
    schema: str = "attention_ffn_residual_spec.v1"
    reference_family: str = "Kimi-inspired local architecture study"
    block_order: BlockOrder = "attention_then_ffn"
    hidden_size: int = 768
    attention_heads: int = 12
    kv_heads: int = 2
    ffn_intermediate_size: int = 2048
    context_window: int = 8192
    use_mla: bool = True
    use_moe_ffn: bool = False
    use_rms_norm: bool = True
    use_qk_clip: bool = True
    residual_scaling: float = 1.0
    stages: tuple[TransformerStageSpec, ...] = field(default_factory=tuple)
    training_stability_notes: tuple[str, ...] = ()
    project_use: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stages"] = [stage.to_dict() for stage in self.stages]
        data["training_stability_notes"] = list(self.training_stability_notes)
        data["project_use"] = list(self.project_use)
        return data


def build_attention_ffn_residual_chain(*, block_order: BlockOrder = "attention_then_ffn") -> tuple[TransformerStageSpec, ...]:
    if block_order == "ffn_then_attention_experiment":
        return (
            TransformerStageSpec("input_norm", "RMSNorm(x)", notes=("Pre-norm keeps gradient flow stable.",)),
            TransformerStageSpec("ffn", "SwiGLU/MoE feed-forward transform", notes=("Useful for task-specific feature expansion before attention experiment.",)),
            TransformerStageSpec("ffn_residual", "x = x + scale * ffn(norm(x))", residual=True),
            TransformerStageSpec("attention_norm", "RMSNorm(x)", notes=("Normalize before attention projection.",)),
            TransformerStageSpec("attention", "MLA/MHA attention with RoPE and optional QK clipping", notes=("Attention routes expanded features across context.",)),
            TransformerStageSpec("attention_residual", "x = x + scale * attn(norm(x))", residual=True),
        )
    return (
        TransformerStageSpec("attention_norm", "RMSNorm(x)", notes=("Pre-norm attention path, production-safe default.",)),
        TransformerStageSpec("attention", "MLA/MHA attention with RoPE and optional QK clipping", notes=("Kimi-style inspiration: long-context attention should be stable and memory-aware.",)),
        TransformerStageSpec("attention_residual", "x = x + scale * attn(norm(x))", residual=True, notes=("Attention residual preserves original token representation.",)),
        TransformerStageSpec("ffn_norm", "RMSNorm(x)", notes=("Second pre-norm before feed-forward transformation.",)),
        TransformerStageSpec("ffn", "SwiGLU dense FFN or sparse MoE FFN", notes=("FFN stores nonlinear task features; MoE can scale capacity without activating all params.",)),
        TransformerStageSpec("ffn_residual", "x = x + scale * ffn(norm(x))", residual=True, notes=("Residual path avoids destructive feature overwrite.",)),
    )


def build_kimi_inspired_local_architecture(
    *,
    block_order: BlockOrder = "attention_then_ffn",
    hidden_size: int = 768,
    context_window: int = 8192,
    use_moe_ffn: bool = False,
) -> AttentionFFNResidualSpec:
    """Return a local-model architecture plan inspired by public Kimi design ideas.

    This is intentionally a design/spec object, not an attempt to clone Kimi.
    It translates useful ideas—long-context attention, residual discipline,
    sparse FFN capacity, and stability clipping—into this project's small-model
    roadmap.
    """

    return AttentionFFNResidualSpec(
        block_order=block_order,
        hidden_size=hidden_size,
        attention_heads=max(1, hidden_size // 64),
        kv_heads=max(1, hidden_size // 384),
        ffn_intermediate_size=int(hidden_size * 8 / 3) if use_moe_ffn else hidden_size * 4,
        context_window=context_window,
        use_mla=True,
        use_moe_ffn=use_moe_ffn,
        use_rms_norm=True,
        use_qk_clip=True,
        residual_scaling=1.0,
        stages=build_attention_ffn_residual_chain(block_order=block_order),
        training_stability_notes=(
            "Use pre-norm residual blocks to reduce deep-network gradient instability.",
            "Use QK/attention-logit clipping or monitoring to prevent attention spikes under pressure prompts.",
            "Keep local middle-layer models small and interpretable before server LoRA/distillation.",
            "Record hallucination-harness failure modes as training/evaluation labels, not as hidden prompt text.",
        ),
        project_use=(
            "middle_model_rule_acceleration: compact residual MLP/attention encoder for routing expensive algorithms",
            "github_corpus_quality_evaluator: attention over repo evidence cards before scalar ranking",
            "semantic_retrieval: slot-aware attention over NeedSlot/CandidateEvidence graph features",
        ),
    )


def render_architecture_markdown(spec: AttentionFFNResidualSpec) -> str:
    lines = [f"# {spec.schema}", "", f"Reference family: {spec.reference_family}", ""]
    lines.append("## Block chain")
    for idx, stage in enumerate(spec.stages, 1):
        residual = " residual" if stage.residual else ""
        lines.append(f"{idx}. **{stage.name}**{residual}: `{stage.operation}`")
        for note in stage.notes:
            lines.append(f"   - {note}")
    lines.append("")
    lines.append("## Stability notes")
    for note in spec.training_stability_notes:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## Project use")
    for item in spec.project_use:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"
