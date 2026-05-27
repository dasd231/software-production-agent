from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class EntityField:
    name: str
    type: str
    required: bool = True
    description: str = ""
    indexed: bool = False
    unique: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EntitySchema:
    name: str
    table: str
    fields: list[EntityField]
    indexes: list[list[str]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "table": self.table,
            "fields": [field.to_dict() for field in self.fields],
            "indexes": self.indexes,
            "constraints": self.constraints,
        }


@dataclass(slots=True)
class StateTransition:
    name: str
    from_state: str
    to_state: str
    actor_roles: list[str]
    condition: str = ""
    side_effects: list[str] = field(default_factory=list)
    idempotency_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PermissionRule:
    role: str
    resource: str
    actions: list[str]
    scope: str
    condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class APIContract:
    method: str
    path: str
    operation: str
    auth: str
    request_schema: dict[str, str]
    response_schema: dict[str, str]
    idempotent: bool = False
    state_transition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompilationFinding:
    severity: str
    code: str
    message: str
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BusinessRuleCompilation:
    schema: str
    domain: str
    source_summary: str
    entities: list[EntitySchema]
    states: list[str]
    transitions: list[StateTransition]
    permissions: list[PermissionRule]
    api_contracts: list[APIContract]
    invariants: list[str]
    runtime_plan: dict[str, Any]
    progressive_enhancement: list[dict[str, Any]]
    findings: list[CompilationFinding]

    @property
    def ok(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ok": self.ok,
            "domain": self.domain,
            "source_summary": self.source_summary,
            "entities": [entity.to_dict() for entity in self.entities],
            "state_machine": {
                "states": self.states,
                "initial_state": self.states[0] if self.states else "",
                "terminal_states": [state for state in self.states if state in {"closed", "rejected", "refunded", "cancelled"}],
                "transitions": [transition.to_dict() for transition in self.transitions],
            },
            "permissions": [permission.to_dict() for permission in self.permissions],
            "api_contracts": [contract.to_dict() for contract in self.api_contracts],
            "invariants": self.invariants,
            "runtime_plan": self.runtime_plan,
            "progressive_enhancement": self.progressive_enhancement,
            "findings": [finding.to_dict() for finding in self.findings],
        }

