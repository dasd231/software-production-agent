from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

SupervisorStatus = Literal["allowed", "denied", "human_required", "sandbox_required"]


@dataclass(slots=True)
class SupervisorContext:
    action_name: str
    args: dict[str, Any]
    workspace: Path | None = None
    granted_permissions: frozenset[str] = frozenset({"*"})
    confirmed_actions: frozenset[str] = frozenset()
    user: str = "agent"
    roles: tuple[str, ...] = ("agent",)
    request_id: str = ""


@dataclass(slots=True)
class SupervisionEvent:
    phase: str
    filter_name: str
    message: str
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SupervisorDecision:
    status: SupervisorStatus = "allowed"
    risk_level: str = "low"
    allowed: bool = True
    requires_human: bool = False
    sandbox_required: bool = False
    sandbox_recommended: bool = False
    reason: str = "allowed"
    recommended_action: str = "execute_normally"
    deny_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    missing_permissions: list[str] = field(default_factory=list)
    audit_events: list[SupervisionEvent] = field(default_factory=list)
    k8s_sandbox: dict[str, Any] = field(default_factory=dict)

    def add_event(self, phase: str, filter_name: str, message: str, *, severity: str = "info", **metadata: Any) -> None:
        self.audit_events.append(
            SupervisionEvent(
                phase=phase,
                filter_name=filter_name,
                message=message,
                severity=severity,
                metadata={k: v for k, v in metadata.items() if v is not None},
            )
        )

    def warn(self, message: str, *, filter_name: str = "supervisor", **metadata: Any) -> None:
        self.warnings.append(message)
        self.add_event("pre_check", filter_name, message, severity="warning", **metadata)

    def deny(self, reason: str, *, filter_name: str = "supervisor", recommended_action: str = "choose_allowed_action") -> None:
        self.allowed = False
        self.status = "denied"
        self.reason = reason
        self.recommended_action = recommended_action
        self.deny_reasons.append(reason)
        self.add_event("pre_check", filter_name, reason, severity="error")

    def require_human(self, reason: str, *, filter_name: str = "supervisor") -> None:
        self.allowed = False
        self.status = "human_required"
        self.requires_human = True
        self.reason = reason
        self.recommended_action = "request_explicit_confirmation"
        self.deny_reasons.append(reason)
        self.add_event("pre_check", filter_name, reason, severity="warning")

    def require_sandbox(self, reason: str, *, filter_name: str = "supervisor") -> None:
        self.allowed = False
        self.status = "sandbox_required"
        self.sandbox_required = True
        self.reason = reason
        self.recommended_action = "dispatch_to_k8s_sandbox"
        self.deny_reasons.append(reason)
        self.add_event("pre_check", filter_name, reason, severity="warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "risk_level": self.risk_level,
            "allowed": self.allowed,
            "requires_human": self.requires_human,
            "sandbox_required": self.sandbox_required,
            "sandbox_recommended": self.sandbox_recommended,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "deny_reasons": list(self.deny_reasons),
            "warnings": list(self.warnings),
            "required_permissions": list(self.required_permissions),
            "missing_permissions": list(self.missing_permissions),
            "audit_events": [event.to_dict() for event in self.audit_events],
            "k8s_sandbox": dict(self.k8s_sandbox),
        }
