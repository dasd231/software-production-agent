from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.supervisor.filter_chain import SupervisorChain, build_default_supervisor_chain
from agent.supervisor.schema import SupervisorContext, SupervisorDecision


def review_action(
    action_name: str,
    args: dict[str, Any],
    *,
    workspace: Path | None = None,
    granted_permissions: frozenset[str] = frozenset({"*"}),
    confirmed_actions: frozenset[str] = frozenset(),
    user: str = "agent",
    roles: tuple[str, ...] = ("agent",),
    request_id: str = "",
    chain: SupervisorChain | None = None,
) -> SupervisorDecision:
    return (chain or build_default_supervisor_chain()).review(
        SupervisorContext(
            action_name=str(action_name),
            args=dict(args or {}),
            workspace=workspace,
            granted_permissions=granted_permissions,
            confirmed_actions=confirmed_actions,
            user=user,
            roles=roles,
            request_id=request_id,
        )
    )
