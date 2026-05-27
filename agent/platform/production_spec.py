from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DatabaseRoleSpec:
    role: str
    local_dev: str
    production: str
    reason: str
    migration: str = "Alembic/Flyway-style versioned migrations"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationSpec:
    name: str
    mechanism: str
    failure_policy: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


@dataclass(frozen=True, slots=True)
class ProductionIntegritySpec:
    schema: str
    auth_database: DatabaseRoleSpec
    production_database: DatabaseRoleSpec
    cache_and_idempotency: DatabaseRoleSpec
    security_verifications: tuple[VerificationSpec, ...]
    idempotency_verifications: tuple[VerificationSpec, ...]
    audit_and_observability: tuple[VerificationSpec, ...]
    secret_management: tuple[str, ...]
    release_gates: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "auth_database": self.auth_database.to_dict(),
            "production_database": self.production_database.to_dict(),
            "cache_and_idempotency": self.cache_and_idempotency.to_dict(),
            "security_verifications": [item.to_dict() for item in self.security_verifications],
            "idempotency_verifications": [item.to_dict() for item in self.idempotency_verifications],
            "audit_and_observability": [item.to_dict() for item in self.audit_and_observability],
            "secret_management": list(self.secret_management),
            "release_gates": list(self.release_gates),
        }


def build_production_integrity_spec(*, service_name: str = "software-production-agent-platform") -> ProductionIntegritySpec:
    return ProductionIntegritySpec(
        schema="production_integrity_spec.v1",
        auth_database=DatabaseRoleSpec(
            role="login_auth_identity",
            local_dev="SQLite only for local smoke tests, or in-memory fake for unit tests",
            production="PostgreSQL primary schema `identity` with users/roles/permissions/sessions/audit_login tables",
            reason="Auth data needs transactions, migrations, constraints, indexes, backup and audit; do not store production auth in local files.",
        ),
        production_database=DatabaseRoleSpec(
            role="business_and_agent_control_plane",
            local_dev="SQLite/PostgreSQL docker compose for developer loops",
            production="PostgreSQL HA cluster for users, tenants, workflow_runs, agent_events, evidence_ledger, idempotency_records, outbox",
            reason="Agent state and business state require ACID, queryability, point-in-time recovery and migration governance.",
        ),
        cache_and_idempotency=DatabaseRoleSpec(
            role="cache_rate_limit_idempotency",
            local_dev="fakeredis/in-memory TTL map in tests",
            production="Redis Cluster for sessions, token blacklist, distributed locks, rate-limit buckets, idempotency short TTL cache",
            reason="Redis handles short-lived, high-QPS coordination; durable idempotency result still lands in PostgreSQL.",
            migration="Redis keys are versioned by prefix; durable table migrations remain in PostgreSQL",
        ),
        security_verifications=(
            VerificationSpec(
                "password_storage",
                "Argon2id or BCrypt with per-password salt; never log raw password; password_hash only",
                "block release if plaintext password can be persisted or logged",
                ("unit test: hash != raw", "log redaction test", "DB column scan fixture"),
            ),
            VerificationSpec(
                "token_security",
                "JWT access token short TTL + refresh rotation; Redis token blacklist/session revocation",
                "401 on expired/revoked token; block if refresh reuse not detected",
                ("expired token test", "logout revocation test", "refresh replay test"),
            ),
            VerificationSpec(
                "rbac_authorization",
                "User-Role-Permission with route permission codes and tenant-aware AuthContext",
                "403 on missing permission; block cross-tenant access",
                ("permission matrix test", "cross-tenant denial test", "admin audit test"),
            ),
            VerificationSpec(
                "input_and_prompt_safety",
                "Pydantic/DTO validation + SkillRuntime ContractGuard + evidence-id requirement for claims",
                "reject malformed body, task hallucination and unknown evidence reference",
                ("schema validation test", "skill guard test", "prompt injection fixture"),
            ),
        ),
        idempotency_verifications=(
            VerificationSpec(
                "http_idempotency_key",
                "Idempotency-Key header hashed with tenant_id/user_id/route/body_hash; PostgreSQL unique constraint stores final response pointer",
                "same key+same body returns same result; same key+different body returns 409",
                ("duplicate request test", "body mismatch test", "concurrent insert test"),
            ),
            VerificationSpec(
                "outbox_dedup",
                "Transactional outbox table with event_id unique; consumers deduplicate by event_id and side_effect_key",
                "message retry is safe; external side effect executed at most once",
                ("consumer retry test", "DLQ test", "side-effect mock call count"),
            ),
            VerificationSpec(
                "workflow_node_idempotency",
                "workflow node idempotency_key = run_id + node + step_index + semantic action hash",
                "resume/retry cannot double-apply production side effects",
                ("checkpoint resume test", "node retry test", "GuardReport replay test"),
            ),
        ),
        audit_and_observability=(
            VerificationSpec(
                "audit_log",
                "append-only audit table for login, permission changes, high-risk action, human approval and external side effect",
                "block release if high-risk action lacks audit row",
                ("audit coverage test", "tamper evidence test"),
            ),
            VerificationSpec(
                "metrics",
                "Prometheus: auth failures, 401/403, idempotency conflicts, guard violations, workflow fail-closed count",
                "alert on spikes and stale workers",
                ("/metrics scrape", "alert rule test"),
            ),
            VerificationSpec(
                "structured_logs",
                "JSON logs with trace_id/run_id/user_id hash/tenant_id hash and recursive secret redaction",
                "block if token/password/api_key appears in logs",
                ("redaction unit test", "sample log grep"),
            ),
        ),
        secret_management=(
            "Local: .env.example only; real secrets ignored by git and injected via environment.",
            "K8s: Secret + sealed-secret/external-secrets; rotate platform API token and JWT signing keys.",
            "Never put database password or API token into Agent evidence, RAG chunks, GraphRAG nodes or logs.",
        ),
        release_gates=(
            "migrations reviewed and rollback tested",
            "auth/RBAC/idempotency tests pass",
            "SkillRuntime anti-hallucination harness pass or explicit risk waiver",
            "Prometheus metrics and audit log enabled",
            "production database backup and restore drill completed",
        ),
    )


def build_database_table_plan() -> dict[str, Any]:
    return {
        "schema": "database_table_plan.v1",
        "identity": [
            "users(id, tenant_id, email, password_hash, status, created_at, updated_at)",
            "roles(id, tenant_id, code, name)",
            "permissions(id, code, resource, action)",
            "user_roles(user_id, role_id, tenant_id)",
            "role_permissions(role_id, permission_id)",
            "sessions(id, user_id, refresh_token_hash, expires_at, revoked_at)",
            "audit_login(id, user_id, tenant_id, result, ip_hash, user_agent_hash, created_at)",
        ],
        "agent_control_plane": [
            "workflow_runs(run_id, tenant_id, user_id, goal, status, current_node, created_at, updated_at)",
            "workflow_events(id, run_id, step_index, node, status, metadata_json, created_at)",
            "guard_reports(id, run_id, node, ok, violation_count, report_json, created_at)",
            "skill_bundles(id, run_id, node, bundle_json, created_at)",
            "evidence_ledger(id, run_id, source_ref, verification_level, content_hash, created_at)",
            "idempotency_records(id, tenant_id, user_id, route, key_hash, body_hash, response_ref, status, expires_at)",
            "outbox_events(event_id, aggregate_id, event_type, payload_json, status, created_at, published_at)",
        ],
        "indexes": [
            "unique users(tenant_id, email)",
            "unique idempotency_records(tenant_id, user_id, route, key_hash)",
            "unique outbox_events(event_id)",
            "index workflow_events(run_id, step_index)",
            "index guard_reports(run_id, node, ok)",
        ],
    }
