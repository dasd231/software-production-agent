"""Compile user intent into a lightweight, validated production workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.resources.registry import discover_resources
from agent.workflows.dry_run import dry_run_workflow
from agent.workflows.spec import validate_workflow_spec


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(token in lower or token in text for token in tokens)


def _goal_tags(goal: str) -> list[str]:
    tags: list[str] = []
    rules = (
        ("auth", ("登录", "登陆", "权限", "角色", "auth", "login", "rbac")),
        ("workflow", ("审批", "流程", "流转", "workflow", "approval")),
        ("frontend-backend", ("前后端", "前端", "后端", "vue", "react", "spring", "api")),
        ("training", ("训练", "微调", "finetune", "fine-tune", "sft", "lora", "qlora")),
        ("crawler", ("github", "爬取", "仓库", "开源", "repo")),
        ("web-research", ("最新", "官网", "文档", "web", "search", "外部")),
        ("asset-publish", ("沉淀", "方案库", "资产", "发布", "复用", "backup", "publish")),
        ("evidence", ("证据", "追溯", "评价", "指标", "ledger", "manifest", "evidence")),
        ("product", ("系统", "平台", "应用", "软件", "管理", "dashboard")),
    )
    for tag, tokens in rules:
        if _has_any(goal, tokens):
            tags.append(tag)
    return tags or ["product"]


def _workflow_from_tags(goal: str, tags: list[str]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [{"id": "context", "chain": "context"}]
    edges: list[list[str]] = []
    previous = "context"
    if "crawler" in tags:
        nodes.append({"id": "crawl", "chain": "github_crawler"})
        edges.append([previous, "crawl"])
        previous = "crawl"
    if "web-research" in tags or "frontend-backend" in tags or "product" in tags or "auth" in tags:
        nodes.append({"id": "research", "chain": "research"})
        edges.append([previous, "research"])
        previous = "research"
    if "training" in tags:
        nodes.append({"id": "train", "chain": "training"})
        edges.append([previous, "train"])
        previous = "train"
    # Publishing is a user-acceptance action in the product UI, not an automatic workflow step.
    # Keep the generated workflow auditable, but do not silently promote unfinished runs into assets.
    if previous != "context" or "evidence" in tags:
        nodes.append({"id": "ledger", "chain": "evidence_ledger"})
        edges.append([previous, "ledger"])
    return {
        "schema": "workflow.v1",
        "version": "intent-compiled.v1",
        "goal": goal,
        "nodes": nodes,
        "edges": edges,
    }


def _resource_suggestions(goal: str, resources: dict[str, Any]) -> list[dict[str, Any]]:
    terms = {part.lower() for part in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", goal)}
    suggestions: list[dict[str, Any]] = []
    for row in resources.get("resources", []):
        haystack = " ".join(
            [
                str(row.get("name", "")),
                str(row.get("summary", "")),
                " ".join(str(x) for x in row.get("tags", [])),
            ]
        ).lower()
        hits = sorted(term for term in terms if term in haystack)
        if hits or row.get("type") in {"chain", "model_provider"}:
            suggestions.append(
                {
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "name": row.get("name"),
                    "path": row.get("path", ""),
                    "matched_terms": hits[:8],
                }
            )
        if len(suggestions) >= 16:
            break
    return suggestions


def _risk_notes(tags: list[str], validation: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if validation.get("network_required"):
        risks.append("network_required: external repo/web evidence needs review")
    if validation.get("writes_files"):
        risks.append("writes_files: generated artifacts must remain inside workspace")
    if "training" in tags:
        risks.append("training_governance_required: license/privacy/secret review remains mandatory")
    if "auth" in tags:
        risks.append("auth_security_required: password/session/RBAC paths need explicit tests")
    if "asset-publish" in tags:
        risks.append("user_acceptance_required: only explicitly satisfied deliveries enter the solution library")
    return risks


def compile_intent(goal: str, workspace: Path, *, roots: tuple[Path, ...] = ()) -> dict[str, Any]:
    clean_goal = " ".join(str(goal or "").split())[:4000]
    tags = _goal_tags(clean_goal)
    workflow = _workflow_from_tags(clean_goal, tags)
    validation = validate_workflow_spec(workflow)
    dry_run = dry_run_workflow(workflow, workspace)
    resources = discover_resources(workspace, roots=roots)
    return {
        "schema": "intent_compilation.v1",
        "goal": clean_goal,
        "intent_tags": tags,
        "workflow": workflow,
        "validation": validation,
        "dry_run": dry_run,
        "resource_suggestions": _resource_suggestions(clean_goal, resources),
        "risk_notes": _risk_notes(tags, validation),
        "operator_role": "approve_or_edit_workflow_before_execution",
        "positioning": "Intent-to-production: user states the goal; system compiles, validates, executes and learns.",
    }
