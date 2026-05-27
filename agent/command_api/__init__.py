"""CommandAPI control plane for keeping a large Agent project coherent.

CommandAPI is a deliberately small architectural layer: every externally
visible capability is represented as a command with owner domain, permissions,
side-effect contract, workflow phase and observability obligations.  It solves
the "large project looseness" problem by making command boundaries explicit.
"""

from agent.command_api.catalog import build_command_api_plan, command_api_to_property_graph

__all__ = ["build_command_api_plan", "command_api_to_property_graph"]
