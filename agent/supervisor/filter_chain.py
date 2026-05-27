from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agent.core.governance import action_governance
from agent.supervisor.schema import SupervisorContext, SupervisorDecision


class SupervisorFilter(Protocol):
    name: str

    def apply(self, context: SupervisorContext, decision: SupervisorDecision) -> SupervisorDecision:
        ...


def _permission_allowed(required: str, granted: frozenset[str]) -> bool:
    if "*" in granted or required in granted:
        return True
    namespace = required.split(":", 1)[0]
    return f"{namespace}:*" in granted


@dataclass(slots=True)
class PermissionSupervisorFilter:
    name: str = "permission_filter"

    def apply(self, context: SupervisorContext, decision: SupervisorDecision) -> SupervisorDecision:
        spec = action_governance(context.action_name)
        missing = [perm for perm in spec.permissions if not _permission_allowed(perm, context.granted_permissions)]
        decision.required_permissions = list(spec.permissions)
        decision.missing_permissions = missing
        decision.risk_level = _max_risk(decision.risk_level, spec.risk_level)
        if missing:
            decision.deny(
                f"missing permissions: {', '.join(missing)}",
                filter_name=self.name,
                recommended_action="request_permission_or_use_allowed_action",
            )
        elif spec.requires_confirmation and context.action_name not in context.confirmed_actions:
            decision.require_human(
                f"action {context.action_name} requires explicit confirmation",
                filter_name=self.name,
            )
        else:
            decision.add_event("pre_check", self.name, "permission check passed", required_permissions=list(spec.permissions))
        return decision


_FORBIDDEN_COMMAND_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\brm\s+-rf\s+/(\s|$)",
        r"\brm\s+-rf\s+~",
        r"\bmkfs(\.|\s|$)",
        r"\bdd\s+.*\bof=/dev/",
        r"\bshutdown\b",
        r"\breboot\b",
        r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",
        r"\bRemove-Item\b.*\b-Recurse\b.*\b(C:\\|/)",
        r"\bcurl\b.*\|\s*(sh|bash)",
        r"\bwget\b.*\|\s*(sh|bash)",
    ]
]

_HUMAN_COMMAND_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bsudo\b",
        r"\bchmod\s+-R\s+777\b",
        r"\bchown\s+-R\b",
        r"\bgit\s+push\s+--force\b",
        r"\bkubectl\s+delete\b",
        r"\bdocker\s+system\s+prune\b",
    ]
]

_SANDBOX_COMMAND_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\btorchrun\b",
        r"\bdeepspeed\b",
        r"\bray\s+(start|submit|job)\b",
        r"\bpython\b.*\b(train|finetune|fine_tune|crawl)\w*\.py\b",
        r"\bpip\s+install\b.*(-r|requirements)",
    ]
]


@dataclass(slots=True)
class CommandRiskSupervisorFilter:
    name: str = "command_risk_filter"

    def apply(self, context: SupervisorContext, decision: SupervisorDecision) -> SupervisorDecision:
        if context.action_name != "run_command":
            return decision
        command = str(context.args.get("command", "") or "")
        timeout = _safe_float(context.args.get("timeout"), 0.0)
        if not command.strip():
            decision.deny("empty command is not allowed", filter_name=self.name)
            return decision
        for pattern in _FORBIDDEN_COMMAND_PATTERNS:
            if pattern.search(command):
                decision.deny(
                    f"command denied by supervisor pattern: {pattern.pattern}",
                    filter_name=self.name,
                    recommended_action="choose_allowed_action",
                )
                decision.risk_level = "critical"
                return decision
        for pattern in _HUMAN_COMMAND_PATTERNS:
            if pattern.search(command) and context.action_name not in context.confirmed_actions:
                decision.require_human(
                    f"command requires human approval: {pattern.pattern}",
                    filter_name=self.name,
                )
                decision.risk_level = _max_risk(decision.risk_level, "high")
                return decision
        sandbox_requested = bool(context.args.get("sandbox") == "k8s" or context.args.get("requires_sandbox"))
        sandbox_hit = any(pattern.search(command) for pattern in _SANDBOX_COMMAND_PATTERNS)
        if sandbox_requested:
            decision.require_sandbox("action explicitly requested k8s sandbox execution", filter_name=self.name)
            decision.risk_level = _max_risk(decision.risk_level, "high")
        elif sandbox_hit or timeout >= 300:
            decision.sandbox_recommended = True
            decision.risk_level = _max_risk(decision.risk_level, "high")
            decision.warn(
                "command should run in k8s sandbox for resource and blast-radius isolation",
                filter_name=self.name,
                timeout=timeout,
            )
        else:
            decision.add_event("pre_check", self.name, "command risk check passed")
        return decision


@dataclass(slots=True)
class PathSafetySupervisorFilter:
    name: str = "path_safety_filter"
    path_arg_names: tuple[str, ...] = ("path", "output_dir", "training_dir", "output_path")

    def apply(self, context: SupervisorContext, decision: SupervisorDecision) -> SupervisorDecision:
        workspace = context.workspace
        if workspace is None:
            return decision
        for arg_name in self.path_arg_names:
            raw = context.args.get(arg_name)
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw)
            resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
            try:
                resolved.relative_to(workspace.resolve())
            except ValueError:
                decision.deny(
                    f"path escapes workspace: {arg_name}={raw}",
                    filter_name=self.name,
                    recommended_action="rewrite_path_inside_workspace",
                )
                decision.risk_level = _max_risk(decision.risk_level, "high")
                return decision
        decision.add_event("pre_check", self.name, "path safety check passed")
        return decision


@dataclass(slots=True)
class ResourceBudgetSupervisorFilter:
    name: str = "resource_budget_filter"
    max_local_timeout_seconds: float = 300.0
    max_write_bytes_without_warning: int = 1_000_000

    def apply(self, context: SupervisorContext, decision: SupervisorDecision) -> SupervisorDecision:
        if context.action_name == "run_command":
            timeout = _safe_float(context.args.get("timeout"), 0.0)
            if timeout > self.max_local_timeout_seconds:
                decision.sandbox_recommended = True
                decision.warn(
                    f"timeout {timeout:.1f}s exceeds local budget; prefer k8s job",
                    filter_name=self.name,
                    timeout=timeout,
                )
        if context.action_name == "write_file":
            content = context.args.get("content")
            if isinstance(content, str) and len(content.encode("utf-8")) > self.max_write_bytes_without_warning:
                decision.warn("large file write should be reviewed or chunked", filter_name=self.name)
        return decision


@dataclass(slots=True)
class SupervisorChain:
    filters: list[SupervisorFilter] = field(default_factory=list)

    def review(self, context: SupervisorContext) -> SupervisorDecision:
        decision = SupervisorDecision()
        decision.add_event("pre_check", "supervisor_chain", "supervision started", action=context.action_name)
        for filter_obj in self.filters:
            decision = filter_obj.apply(context, decision)
            if not decision.allowed:
                break
        if decision.allowed:
            decision.status = "allowed"
            decision.reason = "allowed"
            decision.recommended_action = "execute_normally"
            decision.add_event("pre_check", "supervisor_chain", "supervision allowed action")
        return decision


_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _max_risk(left: str, right: str) -> str:
    return left if _RISK_ORDER.get(left, 0) >= _RISK_ORDER.get(right, 0) else right


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def build_default_supervisor_chain() -> SupervisorChain:
    return SupervisorChain(
        filters=[
            PermissionSupervisorFilter(),
            PathSafetySupervisorFilter(),
            CommandRiskSupervisorFilter(),
            ResourceBudgetSupervisorFilter(),
        ]
    )
