from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

Clock = Callable[[], float]


@dataclass(slots=True)
class AgentTaskRecord:
    task_id: str
    run_id: str
    required_role: str
    payload: dict[str, Any]
    priority: int = 0
    idempotency_key: str = ""
    state: str = "queued"
    assigned_agent_id: str = ""
    lease_id: str = ""
    visible_at: float = 0.0
    lease_expires_at: float = 0.0
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_error: str = ""

    def to_dict(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        data = asdict(self)
        data["visible_in_s"] = max(round(self.visible_at - current, 3), 0.0)
        data["lease_ttl_s"] = max(round(self.lease_expires_at - current, 3), 0.0)
        return data


class InMemoryAgentTaskQueue:
    """Small task queue prototype with lease, visibility timeout and idempotency.

    It is deliberately backend-neutral. The state machine maps to Redis streams or
    Postgres rows, but tests can exercise the reliability semantics without a
    running database.
    """

    def __init__(self, *, clock: Clock | None = None, visibility_timeout_s: float = 30.0) -> None:
        self._clock = clock or time.time
        self._visibility_timeout_s = max(float(visibility_timeout_s), 0.1)
        self._tasks: dict[str, AgentTaskRecord] = {}
        self._idempotency: dict[str, str] = {}
        self._dead_letters: list[AgentTaskRecord] = []
        self._heartbeats: dict[str, dict[str, Any]] = {}

    def heartbeat(self, agent_id: str, *, role: str, load: float = 0.0) -> dict[str, Any]:
        now = self._clock()
        self._heartbeats[str(agent_id)] = {"agent_id": str(agent_id), "role": str(role), "load": float(load), "last_seen": now}
        return {"schema": "agent_heartbeat.v1", **self._heartbeats[str(agent_id)]}

    def submit(
        self,
        *,
        run_id: str,
        required_role: str,
        payload: dict[str, Any],
        priority: int = 0,
        idempotency_key: str = "",
        task_id: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        now = self._clock()
        key = str(idempotency_key or "")
        if key and key in self._idempotency:
            existing = self._tasks.get(self._idempotency[key])
            if existing:
                return {"schema": "agent_task_submit.v1", "accepted": True, "reason": "idempotent_replay", "task": existing.to_dict(now=now)}
        record = AgentTaskRecord(
            task_id=task_id or f"task-{uuid.uuid4().hex[:12]}",
            run_id=str(run_id),
            required_role=str(required_role or "worker"),
            payload=dict(payload or {}),
            priority=int(priority),
            idempotency_key=key,
            visible_at=now,
            created_at=now,
            updated_at=now,
            max_attempts=max(int(max_attempts), 1),
        )
        self._tasks[record.task_id] = record
        if key:
            self._idempotency[key] = record.task_id
        return {"schema": "agent_task_submit.v1", "accepted": True, "reason": "queued", "task": record.to_dict(now=now)}

    def acquire(self, *, agent_id: str, role: str, lease_ttl_s: float | None = None) -> dict[str, Any]:
        now = self._clock()
        ttl = max(float(lease_ttl_s or self._visibility_timeout_s), 0.1)
        candidates = [
            task
            for task in self._tasks.values()
            if task.state in {"queued", "leased"}
            and task.required_role == str(role)
            and task.visible_at <= now
            and (task.state == "queued" or task.lease_expires_at <= now)
        ]
        candidates.sort(key=lambda item: (-item.priority, item.created_at, item.task_id))
        if not candidates:
            return {"schema": "agent_task_acquire.v1", "acquired": False, "reason": "empty", "task": None}
        task = candidates[0]
        task.state = "leased"
        task.assigned_agent_id = str(agent_id)
        task.lease_id = f"lease-{uuid.uuid4().hex[:12]}"
        task.lease_expires_at = now + ttl
        task.visible_at = now + ttl
        task.attempt_count += 1
        task.updated_at = now
        return {"schema": "agent_task_acquire.v1", "acquired": True, "reason": "lease_acquired", "task": task.to_dict(now=now)}

    def renew(self, lease_id: str, *, lease_ttl_s: float | None = None) -> dict[str, Any]:
        now = self._clock()
        task = self._task_by_lease(lease_id)
        if not task:
            return {"schema": "agent_task_renew.v1", "renewed": False, "reason": "lease_not_found"}
        ttl = max(float(lease_ttl_s or self._visibility_timeout_s), 0.1)
        task.lease_expires_at = now + ttl
        task.visible_at = now + ttl
        task.updated_at = now
        return {"schema": "agent_task_renew.v1", "renewed": True, "task": task.to_dict(now=now)}

    def complete(self, lease_id: str, *, result: dict[str, Any] | None = None) -> dict[str, Any]:
        now = self._clock()
        task = self._task_by_lease(lease_id)
        if not task:
            return {"schema": "agent_task_complete.v1", "completed": False, "reason": "lease_not_found"}
        task.state = "completed"
        task.payload = {**task.payload, "result": dict(result or {})}
        task.updated_at = now
        return {"schema": "agent_task_complete.v1", "completed": True, "task": task.to_dict(now=now)}

    def fail(self, lease_id: str, *, error: str, retry: bool = True) -> dict[str, Any]:
        now = self._clock()
        task = self._task_by_lease(lease_id)
        if not task:
            return {"schema": "agent_task_fail.v1", "failed": False, "reason": "lease_not_found"}
        task.last_error = str(error)[:500]
        if retry and task.attempt_count < task.max_attempts:
            task.state = "queued"
            task.assigned_agent_id = ""
            task.lease_id = ""
            task.lease_expires_at = 0.0
            task.visible_at = now
            reason = "requeued"
        else:
            task.state = "dead_letter"
            self._dead_letters.append(task)
            reason = "dead_letter"
        task.updated_at = now
        return {"schema": "agent_task_fail.v1", "failed": True, "reason": reason, "task": task.to_dict(now=now)}

    def reap_expired_leases(self) -> dict[str, Any]:
        now = self._clock()
        requeued = 0
        for task in self._tasks.values():
            if task.state == "leased" and task.lease_expires_at <= now:
                if task.attempt_count >= task.max_attempts:
                    task.state = "dead_letter"
                    self._dead_letters.append(task)
                else:
                    task.state = "queued"
                    task.assigned_agent_id = ""
                    task.lease_id = ""
                    task.visible_at = now
                    requeued += 1
                task.updated_at = now
        return {"schema": "agent_task_reap.v1", "requeued": requeued, "dead_letter_count": len(self._dead_letters)}

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        states: dict[str, int] = {}
        by_role: dict[str, int] = {}
        for task in self._tasks.values():
            states[task.state] = states.get(task.state, 0) + 1
            if task.state in {"queued", "leased"}:
                by_role[task.required_role] = by_role.get(task.required_role, 0) + 1
        return {
            "schema": "agent_task_queue_snapshot.v1",
            "states": states,
            "queue_depth_by_role": by_role,
            "task_count": len(self._tasks),
            "dead_letter_count": len(self._dead_letters),
            "heartbeat_count": len(self._heartbeats),
            "oldest_visible_age_s": self._oldest_visible_age(now),
        }

    def _oldest_visible_age(self, now: float) -> float:
        visible = [task for task in self._tasks.values() if task.state == "queued" and task.visible_at <= now]
        if not visible:
            return 0.0
        return round(now - min(task.created_at for task in visible), 3)

    def _task_by_lease(self, lease_id: str) -> AgentTaskRecord | None:
        for task in self._tasks.values():
            if task.lease_id == str(lease_id) and task.state == "leased":
                return task
        return None


def build_task_queue_backend_plan() -> dict[str, Any]:
    return {
        "schema": "agent_task_queue_backend_plan.v1",
        "state_machine": ["queued", "leased", "completed", "dead_letter"],
        "semantics": [
            "heartbeat freshness identifies live agents",
            "visibility timeout makes crashed-worker tasks visible again",
            "idempotency_key suppresses duplicate side effects",
            "attempt_count and max_attempts bound infinite retries",
            "dead letter queue preserves poison tasks for human/debug review",
        ],
        "postgres_tables": [
            "agent_instance(agent_id, role, status, lease_epoch, last_heartbeat_at, load, metadata)",
            "agent_task(task_id, run_id, required_role, state, priority, assigned_agent_id, visibility_deadline, idempotency_key unique, attempt_count, payload)",
            "agent_dead_letter(dlq_id, task_id, reason, payload, created_at)",
        ],
        "redis_keys": [
            "agent:heartbeat:{agent_id} -> TTL hash",
            "agent:lease:{task_id} -> SET NX PX fencing-token",
            "queue:{role}:{priority} -> stream/list",
            "idempotency:{key} -> completed result pointer",
        ],
        "metrics": [
            "agent_task_queue_depth{role,priority}",
            "agent_task_lease_expired_total{role}",
            "agent_task_dead_letter_total{role,reason}",
            "agent_task_idempotent_replay_total{role}",
            "agent_heartbeat_staleness_seconds{agent_id,role}",
        ],
    }
