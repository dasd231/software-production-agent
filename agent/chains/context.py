"""Context sub-chain for skill, RAG, and MCP enrichment.

The main chain owns orchestration and execution. This sub-chain owns only the
context hints that are safe to inject into state before the Brain decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import AppConfig
from agent.mcp.adapter import default_mcp_capabilities
from agent.rag.unified import retrieve_unified_snippets
from agent.skills.router import suggest_skills


@dataclass(frozen=True)
class ContextChainInput:
    structure: dict[str, Any]
    workspace: Path
    goal: str
    plan: dict[str, Any]
    state: dict[str, Any]
    config: AppConfig


@dataclass(frozen=True)
class ContextChainResult:
    structure: dict[str, Any]
    summary: dict[str, Any]


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def build_context_query(
    goal: str,
    plan_dict: dict[str, Any],
    state_dict: dict[str, Any],
    limit: int = 1200,
) -> str:
    parts: list[str] = []
    if goal.strip():
        parts.append(_clip_text(goal, 400))

    tasks = plan_dict.get("tasks") if isinstance(plan_dict, dict) else []
    if isinstance(tasks, list):
        for task in tasks[:4]:
            task_text = _clip_text(task, 180)
            if task_text:
                parts.append(task_text)

    errors = state_dict.get("errors") if isinstance(state_dict, dict) else []
    if isinstance(errors, list):
        for err in errors[-2:]:
            if not isinstance(err, dict):
                continue
            message = _clip_text(err.get("message", ""), 240)
            stderr = _clip_text(err.get("stderr", ""), 500)
            if message:
                parts.append(message)
            if stderr:
                parts.append(stderr)

    last_result = state_dict.get("last_result") if isinstance(state_dict, dict) else {}
    if isinstance(last_result, dict) and not parts:
        stderr = _clip_text(last_result.get("stderr", ""), 500)
        stdout = _clip_text(last_result.get("stdout", ""), 240)
        if stderr:
            parts.append(stderr)
        elif stdout:
            parts.append(stdout)

    return "\n".join(p for p in parts if p)[:limit]


def _rag_summary_details(rag_hints: Any) -> dict[str, Any]:
    if not isinstance(rag_hints, list):
        return {"rag_paths": [], "rag_truncated": 0, "rag_sources": {}}
    paths: list[str] = []
    truncated = 0
    sources: dict[str, int] = {}
    for hint in rag_hints:
        if not isinstance(hint, dict):
            continue
        path = str(hint.get("path", "")).strip()
        if path and path not in paths:
            paths.append(path)
        if hint.get("truncated"):
            truncated += 1
        source = str(hint.get("source", "local_workspace") or "local_workspace")
        sources[source] = sources.get(source, 0) + 1
    return {"rag_paths": paths[:5], "rag_truncated": truncated, "rag_sources": sources}


def context_enrichment_summary(structure: dict[str, Any]) -> dict[str, Any]:
    rag_hints = structure.get("rag_hints", [])
    summary: dict[str, Any] = {
        "skill_hints": len(structure.get("skill_hints", []))
        if isinstance(structure.get("skill_hints"), list)
        else 0,
        "rag_hints": len(rag_hints) if isinstance(rag_hints, list) else 0,
        "mcp_capabilities": len(structure.get("mcp_capabilities", []))
        if isinstance(structure.get("mcp_capabilities"), list)
        else 0,
    }
    summary.update(_rag_summary_details(rag_hints))
    return summary


def run_context_chain(inp: ContextChainInput) -> ContextChainResult:
    out = dict(inp.structure)
    cfg = inp.config

    if cfg.enable_skill_hints:
        out["skill_hints"] = suggest_skills(
            inp.goal,
            inp.plan,
            inp.state,
            limit=cfg.skill_hints_limit,
        )

    if cfg.enable_rag_hints:
        rag_result = retrieve_unified_snippets(
            inp.workspace,
            build_context_query(inp.goal, inp.plan, inp.state),
            top_k=cfg.rag_hints_top_k,
            learning_dirs=cfg.learning_rag_dirs if cfg.enable_learning_rag else (),
            learning_top_k=cfg.learning_rag_top_k,
            use_learning_bm25=cfg.learning_rag_bm25,
        )
        out["rag_hints"] = rag_result.hints
        out["rag_observability"] = rag_result.summary

    if cfg.enable_mcp_capabilities:
        out["mcp_capabilities"] = default_mcp_capabilities()

    return ContextChainResult(
        structure=out,
        summary=context_enrichment_summary(out),
    )

