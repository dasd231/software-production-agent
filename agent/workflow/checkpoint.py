from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from agent.workflow.schema import WorkflowState, WorkflowStatus, WorkflowTraceEvent


class WorkflowCheckpointer(Protocol):
    def save_state(self, state: WorkflowState) -> None: ...
    def load_state(self, run_id: str) -> WorkflowState | None: ...
    def append_event(self, event: WorkflowTraceEvent) -> None: ...
    def list_events(self, run_id: str | None = None) -> list[WorkflowTraceEvent]: ...


class InMemoryWorkflowCheckpointer:
    def __init__(self) -> None:
        self.states: dict[str, WorkflowState] = {}
        self.events: list[WorkflowTraceEvent] = []

    def save_state(self, state: WorkflowState) -> None:
        self.states[state.run_id] = WorkflowState(
            run_id=state.run_id,
            goal=state.goal,
            data=dict(state.data),
            status=state.status,
            current_node=state.current_node,
            step_index=state.step_index,
            error=state.error,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )

    def load_state(self, run_id: str) -> WorkflowState | None:
        state = self.states.get(run_id)
        if state is None:
            return None
        return WorkflowState(
            run_id=state.run_id,
            goal=state.goal,
            data=dict(state.data),
            status=state.status,
            current_node=state.current_node,
            step_index=state.step_index,
            error=state.error,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )

    def append_event(self, event: WorkflowTraceEvent) -> None:
        self.events.append(event)

    def list_events(self, run_id: str | None = None) -> list[WorkflowTraceEvent]:
        if run_id is None:
            return list(self.events)
        return [event for event in self.events if event.run_id == run_id]


class JsonlWorkflowCheckpointer(InMemoryWorkflowCheckpointer):
    def __init__(self, root: str | Path) -> None:
        super().__init__()
        self.root = Path(root)
        self.state_dir = self.root / "workflow_states"
        self.event_path = self.root / "workflow_events.jsonl"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, state: WorkflowState) -> None:
        super().save_state(state)
        payload = asdict(state)
        payload["status"] = state.status.value
        (self.state_dir / f"{state.run_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_state(self, run_id: str) -> WorkflowState | None:
        path = self.state_dir / f"{run_id}.json"
        if not path.exists():
            return super().load_state(run_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = WorkflowStatus(payload["status"])
        return WorkflowState(**payload)

    def append_event(self, event: WorkflowTraceEvent) -> None:
        super().append_event(event)
        with self.event_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":")) + "\n")

    def list_events(self, run_id: str | None = None) -> list[WorkflowTraceEvent]:
        if not self.event_path.exists():
            return super().list_events(run_id)
        out: list[WorkflowTraceEvent] = []
        with self.event_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                event = WorkflowTraceEvent(**json.loads(line))
                if run_id is None or event.run_id == run_id:
                    out.append(event)
        return out
