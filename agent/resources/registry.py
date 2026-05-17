"""Coze-style resource registry with lightweight local discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.chains.registry import list_chains
from agent.distributed.backends import list_distributed_backends
from agent.distributed.plans import build_distributed_platform_plan
from agent.distributed.workloads import list_distributed_workloads
from agent.integrations.embedding import list_integration_catalog
from agent.llm.providers import PROVIDER_SPECS, resolve_llm_provider
from agent.llm.runtime import model_runtime_status
from agent.scheduler.routing import list_model_pools
from agent.solution_library.manifest import is_solution_library_ready, normalise_solution_manifest


@dataclass(frozen=True)
class ResourceRecord:
    id: str
    type: str
    name: str
    path: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["tags"] = list(self.tags)
        return out


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resource_id(*parts: Any) -> str:
    h = hashlib.blake2b(digest_size=10)
    for part in parts:
        h.update(str(part).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _dedupe_roots(roots: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if not resolved.exists():
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append(resolved)
    return out


def _iter_named_files(roots: list[Path], name: str, *, limit: int = 80) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if root.is_file() and root.name == name:
            candidates = [root]
        else:
            candidates = list(root.glob(name))
            candidates.extend(root.glob(f"*/{name}"))
            candidates.extend(root.glob(f"*/*/{name}"))
        for path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            key = str(resolved)
            if key in seen or not resolved.is_file():
                continue
            seen.add(key)
            found.append(resolved)
            if len(found) >= limit:
                return found
    return found


def _chain_resources() -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for row in list_chains():
        out.append(
            ResourceRecord(
                id=f"chain:{row['name']}",
                type="chain",
                name=str(row["name"]),
                summary=str(row.get("description", "")),
                tags=(str(row.get("evaluation_stage", "")), str(row.get("cost_level", ""))),
                metadata=row,
            )
        )
    return out


def _model_resources() -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for spec in PROVIDER_SPECS.values():
        out.append(
            ResourceRecord(
                id=f"model_provider:{spec.name}",
                type="model_provider",
                name=spec.label,
                summary=f"default={spec.default_model}",
                tags=tuple(spec.models[:6]),
                metadata={
                    "provider": spec.name,
                    "api_key_env": spec.api_key_env,
                    "base_url": spec.base_url,
                    "default_model": spec.default_model,
                    "ui_enabled": spec.ui_enabled,
                    "api_key_required": spec.api_key_required,
                },
            )
        )
    return out


def _model_runtime_resources() -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for spec in PROVIDER_SPECS.values():
        if spec.name != "main_deepseek":
            continue
        provider = resolve_llm_provider(spec.name, "")
        status = model_runtime_status(spec.name, probe=False)
        out.append(
            ResourceRecord(
                id=f"model_runtime:{spec.name}",
                type="model_runtime",
                name=spec.label,
                path=str(provider.base_url or ""),
                summary=f"{status['serving_hint']} model={provider.model}",
                tags=(provider.model, "openai-compatible", "local" if status["local_endpoint"] else "remote"),
                metadata=status,
            )
        )
    return out


def _model_pool_resources() -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for pool in list_model_pools()["pools"]:
        name = str(pool["name"])
        out.append(
            ResourceRecord(
                id=f"model_pool:{name}",
                type="model_pool",
                name=name,
                path=str(pool.get("base_url", "")),
                summary=f"{pool.get('runtime')} max_model_len={pool.get('max_model_len')} concurrency={pool.get('max_concurrency')}",
                tags=tuple(str(x) for x in pool.get("features", [])[:8]),
                metadata=pool,
            )
        )
    return out


def _model_admission_resources() -> list[ResourceRecord]:
    catalog = list_model_pools()
    return [
        ResourceRecord(
            id="model_admission:pool_leases",
            type="model_admission",
            name="model-pool-admission",
            summary="per-pool lease admission, backpressure and high-concurrency isolation",
            tags=("lease", "backpressure", "high_concurrency", "model_gateway"),
            metadata={
                "schema": "model_admission.v1",
                "backend_env": "MODEL_ADMISSION_BACKEND",
                "default_backend": "local",
                "pools": [pool["name"] for pool in catalog["pools"]],
                "api": [
                    "/api/model-admission/status",
                    "/api/model-admission/acquire",
                    "/api/model-admission/release",
                    "/api/model-admission/renew",
                ],
            },
        )
    ]


def _distributed_backend_resources() -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for row in list_distributed_backends():
        out.append(
            ResourceRecord(
                id=f"distributed_backend:{row['name']}",
                type="distributed_backend",
                name=str(row["name"]),
                summary=f"{row.get('execution_plane', '')} dispatch={row.get('dispatch_mode', '')}",
                tags=tuple(str(item) for item in row.get("capabilities", [])[:8]),
                metadata=row,
            )
        )
    plan = build_distributed_platform_plan()
    out.append(
        ResourceRecord(
            id="distributed_plan:enterprise_growth",
            type="distributed_platform_plan",
            name="enterprise-distributed-growth",
            summary=str(plan.get("north_star", "")),
            tags=("ray-first", "spark-later", "flink-when-needed"),
            metadata=plan,
        )
    )
    return out


def _distributed_workload_resources() -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for row in list_distributed_workloads():
        out.append(
            ResourceRecord(
                id=f"distributed_workload:{row['id']}",
                type="distributed_workload",
                name=str(row["label"]),
                summary=str(row.get("description", "")),
                tags=(
                    str(row.get("queue", "")),
                    str(row.get("priority", "")),
                    str(row.get("backend", "")),
                ),
                metadata=row,
            )
        )
    return out


def _integration_resources() -> list[ResourceRecord]:
    catalog = list_integration_catalog()
    out: list[ResourceRecord] = []
    for row in catalog["integrations"]:
        out.append(
            ResourceRecord(
                id=f"integration:{row['id']}",
                type="integration",
                name=str(row["label"]),
                path=str(row.get("homepage", "")),
                summary=str(row.get("description", "")),
                tags=(
                    str(row.get("category", "")),
                    str(row.get("risk_level", "")),
                    *tuple(str(x) for x in row.get("surfaces", [])[:5]),
                    *tuple(str(x) for x in row.get("capabilities", [])[:4]),
                ),
                metadata={
                    "schema": "integration_manifest.v1",
                    "manifest": row,
                    "api": ["/api/integrations", "/api/integrations/embed-plan"],
                    "action": "integration_embed_plan",
                },
            )
        )
    return out


def _solution_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "solution_manifest.json"):
        raw = _safe_json(path)
        if not is_solution_library_ready(raw):
            continue
        raw = normalise_solution_manifest(raw)
        tags = raw.get("retrieval_tags") if isinstance(raw.get("retrieval_tags"), list) else []
        out.append(
            ResourceRecord(
                id=f"solution:{_resource_id(path)}",
                type="solution",
                name=str(raw.get("template") or path.parent.name),
                path=str(path),
                summary=str(raw.get("goal", ""))[:240],
                tags=tuple(str(x) for x in tags[:12]),
                metadata={
                    "stack": raw.get("stack"),
                    "schema_version": raw.get("schema_version") or raw.get("schema"),
                    "quality_score": raw.get("quality_score") or (raw.get("quality", {}) or {}).get("score") if isinstance(raw.get("quality"), dict) else raw.get("quality_score"),
                    "training_eligible": raw.get("training_eligible"),
                    "acceptance_status": raw.get("acceptance_status"),
                    "accepted_by": raw.get("accepted_by"),
                },
            )
        )
    return out


def _learning_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "knowledge_cards.json"):
        run_dir = path.parent
        index_path = run_dir / "vector_index.jsonl"
        promotion = _safe_json(run_dir / "knowledge_promotion.json")
        quality = _safe_json(run_dir / "knowledge_quality_report.json")
        promotion_summary = promotion.get("summary") if isinstance(promotion.get("summary"), dict) else {}
        quality_aggregate = quality.get("aggregate") if isinstance(quality.get("aggregate"), dict) else {}
        cards = []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cards = raw if isinstance(raw, list) else []
        except (OSError, json.JSONDecodeError):
            cards = []
        quality_gated = bool(promotion)
        out.append(
            ResourceRecord(
                id=f"knowledge:{_resource_id(run_dir)}",
                type="knowledge_store",
                name=run_dir.name,
                path=str(run_dir),
                summary=f"{len(cards)} knowledge cards",
                tags=("rag", "learning_run", "quality_gated" if quality_gated else "ungated"),
                metadata={
                    "cards": len(cards),
                    "vector_index": str(index_path) if index_path.exists() else "",
                    "ready": index_path.exists(),
                    "quality_gated": quality_gated,
                    "promoted_repos": promotion_summary.get("promoted"),
                    "rejected_repos": promotion_summary.get("rejected"),
                    "quality_score": quality_aggregate.get("overall_score"),
                    "quality_grade": quality_aggregate.get("grade"),
                },
            )
        )
    return out


def _dataset_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "dataset.jsonl"):
        lines = 0
        try:
            lines = sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
        except OSError:
            lines = 0
        out.append(
            ResourceRecord(
                id=f"dataset:{_resource_id(path)}",
                type="training_dataset",
                name=path.parent.name,
                path=str(path),
                summary=f"{lines} examples",
                tags=("sft", "dataset"),
                metadata={"examples": lines, "run_dir": str(path.parent)},
            )
        )
    return out


def _dataset_snapshot_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "dataset_snapshot_manifest.json"):
        raw = _safe_json(path)
        counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
        out.append(
            ResourceRecord(
                id=f"dataset_snapshot:{_resource_id(path)}",
                type="dataset_snapshot",
                name=str(raw.get("dataset_id") or path.parent.name),
                path=str(path),
                summary=f"train={counts.get('train_examples', 0)} eval={counts.get('eval_examples', 0)}",
                tags=("snapshot", "sharded" if ((raw.get("sharding") or {}).get("enabled")) else "unsharded"),
                metadata=raw,
            )
        )
    return out


def _model_version_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "model_version_manifest.json"):
        raw = _safe_json(path)
        out.append(
            ResourceRecord(
                id=f"model_version:{_resource_id(path)}",
                type="model_version",
                name=str(raw.get("model_version") or path.parent.name),
                path=str(path),
                summary=f"{raw.get('role', '')} base={raw.get('base_model', '')}",
                tags=tuple(
                    str(x)
                    for x in (
                        raw.get("role", ""),
                        raw.get("rollout_stage", ""),
                        raw.get("adapter_name", ""),
                    )
                    if str(x).strip()
                ),
                metadata=raw,
            )
        )
    return out


def _model_evaluation_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "model_evaluation_report.json"):
        raw = _safe_json(path)
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        out.append(
            ResourceRecord(
                id=f"model_evaluation:{_resource_id(path)}",
                type="model_evaluation",
                name=str(raw.get("label") or path.parent.name),
                path=str(path),
                summary=f"score={summary.get('overall_score', 0.0)} grade={summary.get('grade', '')}",
                tags=("benchmark", str(summary.get("grade", ""))),
                metadata=raw,
            )
        )
    return out


def _model_promotion_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "model_promotion_decision.json"):
        raw = _safe_json(path)
        candidate = raw.get("candidate") if isinstance(raw.get("candidate"), dict) else {}
        out.append(
            ResourceRecord(
                id=f"model_promotion:{_resource_id(path)}",
                type="model_promotion_decision",
                name=str(candidate.get("model_version") or candidate.get("label") or path.parent.name),
                path=str(path),
                summary=f"{raw.get('status', '')} passed={raw.get('passed', False)}",
                tags=tuple(
                    str(x)
                    for x in (
                        raw.get("status", ""),
                        candidate.get("benchmark_id", ""),
                    )
                    if str(x).strip()
                ),
                metadata=raw,
            )
        )
    return out


def _training_job_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "training_job_manifest.json"):
        raw = _safe_json(path)
        out.append(
            ResourceRecord(
                id=f"training_job:{_resource_id(path)}",
                type="training_job",
                name=str(raw.get("job_id") or path.parent.name),
                path=str(path),
                summary=f"{raw.get('backend', '')} status={raw.get('current_status', '')}",
                tags=tuple(
                    str(x)
                    for x in (
                        raw.get("backend", ""),
                        raw.get("execution_target", ""),
                        raw.get("current_status", ""),
                    )
                    if str(x).strip()
                ),
                metadata=raw,
            )
        )
    return out


def _distributed_job_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "distributed_job_manifest.json"):
        raw = _safe_json(path)
        out.append(
            ResourceRecord(
                id=f"distributed_job:{_resource_id(path)}",
                type="distributed_job",
                name=str(raw.get("job_id") or path.parent.name),
                path=str(path),
                summary=f"{raw.get('backend', '')} {raw.get('workload', '')} status={raw.get('current_status', '')}",
                tags=tuple(
                    str(x)
                    for x in (
                        raw.get("backend", ""),
                        raw.get("workload", ""),
                        raw.get("queue", ""),
                        raw.get("current_status", ""),
                    )
                    if str(x).strip()
                ),
                metadata=raw,
            )
        )
    return out


def _run_manifest_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "run_manifest.json"):
        raw = _safe_json(path)
        out.append(
            ResourceRecord(
                id=f"run:{raw.get('manifest_id') or _resource_id(path)}",
                type="run_manifest",
                name=str(raw.get("kind") or path.parent.name),
                path=str(path),
                summary=str(raw.get("created_at", "")),
                tags=(str(raw.get("kind", "")), str((raw.get("evaluation") or {}).get("grade", ""))),
                metadata={
                    "kind": raw.get("kind"),
                    "manifest_id": raw.get("manifest_id"),
                    "evaluation_score": (raw.get("evaluation") or {}).get("overall_score") if isinstance(raw.get("evaluation"), dict) else None,
                },
            )
        )
    return out


def _evidence_ledger_resources(roots: list[Path]) -> list[ResourceRecord]:
    out: list[ResourceRecord] = []
    for path in _iter_named_files(roots, "evidence_ledger.json"):
        raw = _safe_json(path)
        summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
        by_type = summary.get("by_type") if isinstance(summary.get("by_type"), dict) else {}
        out.append(
            ResourceRecord(
                id=f"evidence:{_resource_id(path)}",
                type="evidence_ledger",
                name=path.parent.name,
                path=str(path),
                summary=f"{int(summary.get('total', 0) or 0)} evidence entries",
                tags=tuple(str(k) for k in sorted(by_type)[:8]),
                metadata={
                    "created_at": raw.get("created_at"),
                    "entries": summary.get("total", 0),
                    "by_type": by_type,
                },
            )
        )
    return out


def discover_resources(workspace: Path, *, roots: tuple[Path, ...] = (), type_filter: str = "") -> dict[str, Any]:
    project = _project_root()
    search_roots = _dedupe_roots(
        [
            workspace,
            workspace.parent,
            project / "product_runs",
            project / "learning_runs",
            project / "training_runs",
            project / "model_runs",
            project / "model_evals",
            project / "crawl_runs",
            *roots,
        ]
    )
    resources: list[ResourceRecord] = []
    resources.extend(_chain_resources())
    resources.extend(_model_resources())
    resources.extend(_model_runtime_resources())
    resources.extend(_model_pool_resources())
    resources.extend(_model_admission_resources())
    resources.extend(_distributed_backend_resources())
    resources.extend(_distributed_workload_resources())
    resources.extend(_integration_resources())
    resources.extend(_solution_resources(search_roots))
    resources.extend(_learning_resources(search_roots))
    resources.extend(_dataset_resources(search_roots))
    resources.extend(_dataset_snapshot_resources(search_roots))
    resources.extend(_model_version_resources(search_roots))
    resources.extend(_model_evaluation_resources(search_roots))
    resources.extend(_model_promotion_resources(search_roots))
    resources.extend(_training_job_resources(search_roots))
    resources.extend(_distributed_job_resources(search_roots))
    resources.extend(_run_manifest_resources(search_roots))
    resources.extend(_evidence_ledger_resources(search_roots))
    rows = [row.to_dict() for row in resources if not type_filter or row.type == type_filter]
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["type"])] = counts.get(str(row["type"]), 0) + 1
    return {
        "schema": "resource_registry.v1",
        "workspace": str(workspace.resolve()),
        "roots": [str(root) for root in search_roots],
        "type_filter": type_filter,
        "summary": {"total": len(rows), "by_type": counts},
        "resources": rows,
    }
