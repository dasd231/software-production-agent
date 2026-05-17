"""Backward-compatible entrypoints for context enrichment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.chains.context import (
    ContextChainInput,
    build_context_query,
    context_enrichment_summary,
    run_context_chain,
)
from agent.config import AppConfig


def enrich_structure(
    structure: dict[str, Any],
    *,
    workspace: Path,
    goal: str,
    plan_dict: dict[str, Any],
    state_dict: dict[str, Any],
    config: AppConfig,
) -> dict[str, Any]:
    result = run_context_chain(
        ContextChainInput(
            structure=structure,
            workspace=workspace,
            goal=goal,
            plan=plan_dict,
            state=state_dict,
            config=config,
        )
    )
    return result.structure


def enrichment_summary(structure: dict[str, Any]) -> dict[str, Any]:
    return context_enrichment_summary(structure)


__all__ = [
    "build_context_query",
    "enrich_structure",
    "enrichment_summary",
]

