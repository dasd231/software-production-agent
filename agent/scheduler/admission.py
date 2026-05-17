"""Model-pool admission control and lease accounting.

This module protects high-concurrency serving paths before they touch a model
runtime. It is intentionally backend-neutral: the in-process controller is
enough for tests and single-replica deployments, while the schema maps cleanly
to Redis, Postgres advisory locks, or a workflow queue in production.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from agent.scheduler.routing import DEFAULT_POOLS, build_model_route_plan


Clock = Callable[[], float]


@dataclass(frozen=True)
class LeaseRecord:
    lease_id: str
    pool: str
    queue_key: str
    created_at: float
    expires_at: float
    token_estimate: dict[str, Any]
    business_type: str
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    route_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        out = asdict(self)
        out["ttl_remaining_s"] = max(round(self.expires_at - current, 3), 0.0)
        return out


def _pool_limit_env_name(pool_name: str) -> str:
    return f"MODEL_{pool_name.upper()}_MAX_CONCURRENCY"


def _effective_concurrency(pool_name: str, overrides: dict[str, int] | None = None) -> int:
    if overrides and pool_name in overrides:
        return max(int(overrides[pool_name]), 0)
    raw = os.environ.get(_pool_limit_env_name(pool_name), "").strip()
    if raw:
        try:
            return max(int(raw), 0)
        except ValueError:
            pass
    return DEFAULT_POOLS[pool_name].max_concurrency


def _bounded_ttl(pool_name: str, requested_ttl_s: float | None) -> float:
    default_ttl = float(DEFAULT_POOLS[pool_name].timeout_s)
    if requested_ttl_s is None:
        return default_ttl
    try:
        value = float(requested_ttl_s)
    except (TypeError, ValueError):
        return default_ttl
    if value <= 0:
        return default_ttl
    return min(value, default_ttl)


class PoolAdmissionController:
    """Thread-safe lease controller for model-pool admission."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        limit_overrides: dict[str, int] | None = None,
        backend: str | None = None,
    ) -> None:
        self._clock = clock or time.time
        self._limit_overrides = dict(limit_overrides or {})
        self._backend = backend or os.environ.get("MODEL_ADMISSION_BACKEND", "local")
        self._leases: dict[str, LeaseRecord] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def backend(self) -> str:
        return self._backend

    def _cleanup_locked(self, now: float) -> None:
        expired = [lease_id for lease_id, lease in self._leases.items() if lease.expires_at <= now]
        for lease_id in expired:
            lease = self._leases.pop(lease_id, None)
            if lease and lease.idempotency_key:
                self._idempotency.pop(lease.idempotency_key, None)

    def _active_counts_locked(self) -> dict[str, int]:
        counts = {name: 0 for name in DEFAULT_POOLS}
        for lease in self._leases.values():
            counts[lease.pool] = counts.get(lease.pool, 0) + 1
        return counts

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            counts = self._active_counts_locked()
            pools = []
            for name in sorted(DEFAULT_POOLS):
                limit = _effective_concurrency(name, self._limit_overrides)
                active = counts.get(name, 0)
                pools.append(
                    {
                        "pool": name,
                        "active_leases": active,
                        "max_concurrency": limit,
                        "available": max(limit - active, 0),
                        "saturated": active >= limit,
                        "queue_key": f"model:{name}:{DEFAULT_POOLS[name].priority_class}",
                    }
                )
            return {
                "schema": "model_admission_status.v1",
                "backend": self._backend,
                "leases_total": len(self._leases),
                "pools": pools,
                "notes": [
                    "local backend is per-process; use Redis or workflow queue for multi-replica hard limits",
                    "expired leases are reclaimed on each admission/status call",
                ],
            }

    def acquire(
        self,
        goal: str,
        prompt: str = "",
        *,
        max_output_tokens: int | None = None,
        business_type: str = "",
        require_json: bool = False,
        idempotency_key: str = "",
        lease_ttl_s: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route_plan = build_model_route_plan(
            goal,
            prompt,
            max_output_tokens=max_output_tokens,
            business_type=business_type,
            require_json=require_json,
        )
        selected_pool = str(route_plan["selected_pool"])
        queue_key = str(route_plan["queue_policy"]["queue_key"])
        now = self._clock()

        with self._lock:
            self._cleanup_locked(now)
            if not bool(route_plan.get("admission", {}).get("admitted")):
                return self._result(
                    admitted=False,
                    reason="route_blocked",
                    route_plan=route_plan,
                    retry_after_s=None,
                    lease=None,
                    pool_state=self._pool_state_locked(selected_pool),
                )

            if idempotency_key:
                existing_id = self._idempotency.get(idempotency_key)
                existing = self._leases.get(existing_id or "")
                if existing:
                    replay_plan = existing.route_plan or route_plan
                    return self._result(
                        admitted=True,
                        reason="idempotent_replay",
                        route_plan=replay_plan,
                        retry_after_s=0.0,
                        lease=existing.to_dict(now),
                        pool_state=self._pool_state_locked(existing.pool),
                    )

            pool_state = self._pool_state_locked(selected_pool)
            if pool_state["active_leases"] >= pool_state["max_concurrency"]:
                retry_after = self._retry_after_locked(selected_pool, now)
                return self._result(
                    admitted=False,
                    reason="pool_saturated",
                    route_plan=route_plan,
                    retry_after_s=retry_after,
                    lease=None,
                    pool_state=pool_state,
                )

            ttl = _bounded_ttl(selected_pool, lease_ttl_s)
            lease = LeaseRecord(
                lease_id=str(uuid.uuid4()),
                pool=selected_pool,
                queue_key=queue_key,
                created_at=now,
                expires_at=now + ttl,
                token_estimate=dict(route_plan["token_estimate"]),
                business_type=str(route_plan["business_type"]["type"]),
                idempotency_key=idempotency_key,
                metadata=dict(metadata or {}),
                route_plan=dict(route_plan),
            )
            self._leases[lease.lease_id] = lease
            if idempotency_key:
                self._idempotency[idempotency_key] = lease.lease_id
            return self._result(
                admitted=True,
                reason="lease_acquired",
                route_plan=route_plan,
                retry_after_s=0.0,
                lease=lease.to_dict(now),
                pool_state=self._pool_state_locked(selected_pool),
            )

    def release(self, lease_id: str) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            lease = self._leases.pop(str(lease_id or ""), None)
            if lease and lease.idempotency_key:
                self._idempotency.pop(lease.idempotency_key, None)
            return {
                "schema": "model_admission_release.v1",
                "released": bool(lease),
                "lease_id": str(lease_id or ""),
                "lease": lease.to_dict(now) if lease else None,
                "status": self.snapshot(),
            }

    def renew(self, lease_id: str, *, lease_ttl_s: float | None = None) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            lease = self._leases.get(str(lease_id or ""))
            if not lease:
                return {
                    "schema": "model_admission_renewal.v1",
                    "renewed": False,
                    "lease_id": str(lease_id or ""),
                    "lease": None,
                }
            ttl = _bounded_ttl(lease.pool, lease_ttl_s)
            renewed = LeaseRecord(
                lease_id=lease.lease_id,
                pool=lease.pool,
                queue_key=lease.queue_key,
                created_at=lease.created_at,
                expires_at=now + ttl,
                token_estimate=lease.token_estimate,
                business_type=lease.business_type,
                idempotency_key=lease.idempotency_key,
                metadata=lease.metadata,
                route_plan=lease.route_plan,
            )
            self._leases[lease.lease_id] = renewed
            return {
                "schema": "model_admission_renewal.v1",
                "renewed": True,
                "lease_id": lease.lease_id,
                "lease": renewed.to_dict(now),
            }

    def _pool_state_locked(self, pool_name: str) -> dict[str, Any]:
        counts = self._active_counts_locked()
        limit = _effective_concurrency(pool_name, self._limit_overrides)
        active = counts.get(pool_name, 0)
        return {
            "pool": pool_name,
            "active_leases": active,
            "max_concurrency": limit,
            "available": max(limit - active, 0),
            "saturated": active >= limit,
        }

    def _retry_after_locked(self, pool_name: str, now: float) -> float:
        expiries = [lease.expires_at for lease in self._leases.values() if lease.pool == pool_name]
        if not expiries:
            return 1.0
        return max(round(min(expiries) - now, 3), 0.25)

    def _result(
        self,
        *,
        admitted: bool,
        reason: str,
        route_plan: dict[str, Any],
        retry_after_s: float | None,
        lease: dict[str, Any] | None,
        pool_state: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": "model_admission.v1",
            "admitted": admitted,
            "reason": reason,
            "retry_after_s": retry_after_s,
            "lease": lease,
            "pool_state": pool_state,
            "route_plan": route_plan,
            "backpressure": {
                "queue_key": route_plan["queue_policy"]["queue_key"],
                "action": "forward_to_model_gateway" if admitted else "reject_or_retry_later",
                "http_status": 200 if admitted else 429,
            },
        }


_GLOBAL_CONTROLLER = PoolAdmissionController()


def get_global_admission_controller() -> PoolAdmissionController:
    return _GLOBAL_CONTROLLER
