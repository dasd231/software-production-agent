"""Adaptive workflow runtime for software-production-agent.

This package brings a LangGraph-inspired architecture into the project without
making LangGraph a hard dependency:

- state graph execution
- conditional routing
- checkpoint/resume
- human interrupt gate
- trace/reward collection
- optimizer-driven policy updates

It reuses the existing agent.decision layer instead of replacing it.
"""

from agent.workflow.project_graph import build_project_workflow, run_project_workflow_demo
from agent.workflow.dataset import (
    RouteDatasetSummary,
    RouteTrainingExample,
    build_route_training_examples,
    write_route_training_dataset,
    write_route_training_dataset_from_agent_events,
)
from agent.workflow.event_bridge import agent_events_to_workflow_traces, load_workflow_traces_from_agent_events
from agent.workflow.enterprise import (
    compile_enterprise_workflow,
    default_bioying_research_workflow,
    enterprise_contract_to_property_graph,
    import_dify_workflow,
    query_enterprise_workflow_contract,
)
from agent.workflow.interview import build_interview_readiness_report
from agent.workflow.loop_graph import (
    AgentLoopGraphAnalysis,
    AgentLoopGraphSpec,
    analyze_agent_loop_events,
    analyze_agent_loop_events_file,
    build_agent_loop_graph_spec,
)
from agent.workflow.optimizer import WorkflowOptimizer
from agent.workflow.policy_store import PolicyRecord, PolicyStore
from agent.workflow.replay import ReplayReport, replay_logged_policy
from agent.workflow.rollout import CanaryPlan, build_canary_plan
from agent.workflow.schema import WorkflowPolicy, WorkflowState, WorkflowStatus
from agent.workflow.spec import WorkflowSpec, describe_compiled_workflow

__all__ = [
    "WorkflowPolicy",
    "WorkflowState",
    "WorkflowStatus",
    "WorkflowOptimizer",
    "PolicyRecord",
    "PolicyStore",
    "CanaryPlan",
    "ReplayReport",
    "WorkflowSpec",
    "AgentLoopGraphSpec",
    "AgentLoopGraphAnalysis",
    "RouteTrainingExample",
    "RouteDatasetSummary",
    "build_canary_plan",
    "replay_logged_policy",
    "describe_compiled_workflow",
    "build_agent_loop_graph_spec",
    "analyze_agent_loop_events",
    "analyze_agent_loop_events_file",
    "build_route_training_examples",
    "write_route_training_dataset",
    "write_route_training_dataset_from_agent_events",
    "agent_events_to_workflow_traces",
    "load_workflow_traces_from_agent_events",
    "build_interview_readiness_report",
    "compile_enterprise_workflow",
    "default_bioying_research_workflow",
    "enterprise_contract_to_property_graph",
    "import_dify_workflow",
    "query_enterprise_workflow_contract",
    "build_project_workflow",
    "run_project_workflow_demo",
]


