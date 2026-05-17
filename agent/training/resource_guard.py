"""Cooperative GPU admission for shared training servers."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_training_resource_policy(
    *,
    profile: str = "shared_conservative",
    gpu_count: int = 1,
    max_gpu_memory_gb: float = 12.0,
    cpu_threads: int = 4,
) -> dict[str, Any]:
    """Return the default cooperative policy for a shared single-GPU server."""

    normalized_profile = str(profile or "shared_conservative")
    if normalized_profile != "shared_conservative":
        normalized_profile = "shared_conservative"
    return {
        "schema": "training_resource_policy.v1",
        "profile": normalized_profile,
        "intent": "avoid starting a training job while another user is actively consuming the shared GPU",
        "job_limits": {
            "gpu_count": max(int(gpu_count), 0),
            "max_gpu_memory_gb": max(float(max_gpu_memory_gb), 0.0),
            "cpu_threads": max(int(cpu_threads), 1),
            "data_loader_workers": 2,
        },
        "launch_admission": {
            "max_gpu_utilization_pct": 20,
            "max_gpu_memory_used_gb": 2.0,
            "min_gpu_memory_free_gb": max(float(max_gpu_memory_gb), 0.0),
            "max_compute_processes": 0,
            "block_if_compute_processes_present": True,
        },
        "environment": {
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
            "OMP_NUM_THREADS": str(max(int(cpu_threads), 1)),
            "MKL_NUM_THREADS": str(max(int(cpu_threads), 1)),
            "TOKENIZERS_PARALLELISM": "false",
        },
        "notes": [
            "This is a cooperative gate, not a hard GPU quota enforced by the driver.",
            "The launcher refuses to start when another compute process is already visible.",
            "The first training round should stay conservative on a shared RTX-class server.",
        ],
    }


def _default_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)


def _parse_gpu_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 5:
            continue
        try:
            rows.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_total_mb": int(parts[2]),
                    "memory_used_mb": int(parts[3]),
                    "utilization_gpu_pct": int(parts[4]),
                }
            )
        except ValueError:
            continue
    return rows


def _parse_process_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 4:
            continue
        try:
            rows.append(
                {
                    "gpu_uuid": parts[0],
                    "pid": int(parts[1]),
                    "process_name": parts[2],
                    "used_memory_mb": int(parts[3]),
                }
            )
        except ValueError:
            continue
    return rows


def probe_gpu_inventory(*, runner: Runner | None = None) -> dict[str, Any]:
    """Probe GPU inventory and visible compute processes via ``nvidia-smi``."""

    run = runner or _default_runner
    gpu_cmd = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    process_cmd = [
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
        "--format=csv,noheader,nounits",
    ]
    try:
        gpu_result = run(gpu_cmd)
    except Exception as exc:
        return {
            "schema": "training_gpu_probe.v1",
            "checked": False,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "gpus": [],
            "compute_processes": [],
        }
    if int(getattr(gpu_result, "returncode", 1) or 0) != 0:
        return {
            "schema": "training_gpu_probe.v1",
            "checked": True,
            "ok": False,
            "error": str(getattr(gpu_result, "stderr", "") or getattr(gpu_result, "stdout", ""))[:300],
            "gpus": [],
            "compute_processes": [],
        }
    try:
        process_result = run(process_cmd)
        process_rows = _parse_process_rows(process_result.stdout) if process_result.returncode == 0 else []
    except Exception:
        process_rows = []
    gpu_rows = _parse_gpu_rows(getattr(gpu_result, "stdout", ""))
    return {
        "schema": "training_gpu_probe.v1",
        "checked": True,
        "ok": bool(gpu_rows),
        "gpus": gpu_rows,
        "compute_processes": process_rows,
    }


def evaluate_training_resource_admission(
    *,
    policy: dict[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate whether a shared server is currently safe for a new training launch."""

    admission = policy.get("launch_admission") if isinstance(policy.get("launch_admission"), dict) else {}
    gpus = probe.get("gpus") if isinstance(probe.get("gpus"), list) else []
    processes = probe.get("compute_processes") if isinstance(probe.get("compute_processes"), list) else []
    blockers: list[str] = []
    selected_gpu: dict[str, Any] = {}
    if not bool(probe.get("ok")):
        blockers.append("gpu_probe_failed")
    elif not gpus:
        blockers.append("no_gpu_visible")
    else:
        selected_gpu = min(
            (row for row in gpus if isinstance(row, dict)),
            key=lambda row: (int(row.get("memory_used_mb", 0) or 0), int(row.get("utilization_gpu_pct", 0) or 0)),
        )
        total_mb = int(selected_gpu.get("memory_total_mb", 0) or 0)
        used_mb = int(selected_gpu.get("memory_used_mb", 0) or 0)
        free_gb = max(total_mb - used_mb, 0) / 1024.0
        used_gb = used_mb / 1024.0
        if int(selected_gpu.get("utilization_gpu_pct", 0) or 0) > int(admission.get("max_gpu_utilization_pct", 100) or 100):
            blockers.append("gpu_utilization_above_shared_threshold")
        if used_gb > float(admission.get("max_gpu_memory_used_gb", float("inf")) or float("inf")):
            blockers.append("gpu_memory_already_in_use")
        if free_gb < float(admission.get("min_gpu_memory_free_gb", 0.0) or 0.0):
            blockers.append("insufficient_free_gpu_memory")
        if bool(admission.get("block_if_compute_processes_present", False)) and len(processes) > int(
            admission.get("max_compute_processes", 0) or 0
        ):
            blockers.append("foreign_compute_processes_present")
    return {
        "schema": "training_resource_admission.v1",
        "admitted": not blockers,
        "blockers": blockers,
        "selected_gpu": selected_gpu,
        "visible_compute_processes": len(processes),
        "policy_profile": str(policy.get("profile", "") or ""),
    }


def run_server_resource_preflight(
    *,
    policy: dict[str, Any] | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    resolved_policy = dict(policy or build_training_resource_policy())
    probe = probe_gpu_inventory(runner=runner)
    admission = evaluate_training_resource_admission(policy=resolved_policy, probe=probe)
    return {
        "schema": "training_server_preflight.v1",
        "checked_at": _now(),
        "policy": resolved_policy,
        "probe": probe,
        "admission": admission,
    }


def dumps_preflight(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
