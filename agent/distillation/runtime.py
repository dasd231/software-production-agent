"""Runtime adapter for bounded teacher-model execution."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from agent.llm.providers import create_openai_compatible_client, resolve_llm_provider


CompletionFn = Callable[[dict[str, Any]], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def _extract_first_json_object(text: str) -> dict[str, Any]:
    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].strip()
    try:
        raw = json.loads(candidate)
    except json.JSONDecodeError:
        raw = None
    if isinstance(raw, dict):
        return raw

    start = -1
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(candidate):
        if start < 0:
            if char != "{":
                continue
            start = index
            depth = 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                raw = json.loads(candidate[start : index + 1])
                if isinstance(raw, dict):
                    return raw
                break
    raise ValueError("teacher response did not contain a JSON object")


def _normalise_citations(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        if not path:
            continue
        row: dict[str, Any] = {"path": path}
        for key in ("line", "start_line", "end_line"):
            value = item.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value > 0:
                row[key] = value
        rows.append(row)
    return rows


def _default_completion(
    request: dict[str, Any],
    *,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    provider = resolve_llm_provider(str(request.get("provider", "") or ""), str(request.get("model", "") or ""))
    client = create_openai_compatible_client(provider, timeout=timeout, max_retries=max_retries)
    completion = client.chat.completions.create(
        model=provider.model,
        messages=request.get("messages") if isinstance(request.get("messages"), list) else [],
        temperature=float(request.get("temperature", 0.0) or 0.0),
        max_tokens=max(int(request.get("max_output_tokens", 1024) or 1024), 1),
    )
    usage = getattr(completion, "usage", None)
    return {
        "content": str((completion.choices[0].message.content or "") if completion.choices else ""),
        "usage": {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        },
    }


def run_teacher_execution(
    *,
    execution_plan: dict[str, Any],
    completion_fn: CompletionFn | None = None,
    timeout: float = 90.0,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Execute a validated teacher plan, or emit a side-effect-free dry-run result."""

    requests = execution_plan.get("requests") if isinstance(execution_plan.get("requests"), list) else []
    mode = str(execution_plan.get("mode", "") or "dry_run")
    safety = execution_plan.get("safety") if isinstance(execution_plan.get("safety"), dict) else {}
    plan_ok = bool(execution_plan.get("validation", {}).get("ok"))
    makes_remote_calls = bool(safety.get("makes_remote_calls"))
    records: list[dict[str, Any]] = []
    teacher_outputs: list[dict[str, Any]] = []
    teacher_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if mode == "live" and (not plan_ok or not makes_remote_calls):
        blockers = list(execution_plan.get("validation", {}).get("blockers", []))
        if not plan_ok and "invalid_execution_plan" not in blockers:
            blockers.append("invalid_execution_plan")
        if not makes_remote_calls and "live_mode_not_explicitly_authorized" not in blockers:
            blockers.append("live_mode_not_explicitly_authorized")
        return {
            "schema": "teacher_execution_result.v1",
            "created_at": _now(),
            "execution_plan_id": str(execution_plan.get("execution_plan_id", "") or ""),
            "distillation_id": str(execution_plan.get("distillation_id", "") or ""),
            "mode": mode,
            "counts": {
                "requests": len(requests),
                "completed_requests": 0,
                "failed_requests": 0,
                "skipped_requests": len(requests),
                "teacher_outputs": 0,
            },
            "request_results": [],
            "teacher_outputs": [],
            "usage": usage_totals,
            "validation": {"ok": False, "blockers": blockers},
        }

    for request in requests:
        started = time.perf_counter()
        base_record = {
            "request_id": str(request.get("request_id", "") or ""),
            "prompt_id": str(request.get("prompt_id", "") or ""),
            "teacher_id": str(request.get("teacher_id", "") or ""),
            "teacher_task_id": str(request.get("teacher_task_id", "") or ""),
            "provider": str(request.get("provider", "") or ""),
            "model": str(request.get("model", "") or ""),
        }
        if mode != "live":
            records.append(
                {
                    **base_record,
                    "status": "skipped_dry_run",
                    "latency_ms": 0.0,
                    "error": "",
                }
            )
            continue
        try:
            completion = (
                completion_fn(request)
                if completion_fn is not None
                else _default_completion(request, timeout=max(float(timeout), 0.1), max_retries=max(int(max_retries), 0))
            )
            content = str(completion.get("content", "") or "")
            payload = _extract_first_json_object(content)
            citations = _normalise_citations(payload.get("citations"))
            usage = completion.get("usage") if isinstance(completion.get("usage"), dict) else {}
            normalized_usage = {
                key: int(usage.get(key, 0) or 0)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
            for key, value in normalized_usage.items():
                usage_totals[key] += value
            teacher_output = {
                "teacher_id": base_record["teacher_id"],
                "task_id": base_record["teacher_task_id"],
                "prompt_id": base_record["prompt_id"],
                "instruction": str(request.get("instruction", "") or ""),
                "input": str(request.get("input", "") or ""),
                "output": str(payload.get("output", "") or "").strip(),
                "citations": citations,
                "metadata": {
                    "request_id": base_record["request_id"],
                    "provider": base_record["provider"],
                    "model": base_record["model"],
                    "usage": normalized_usage,
                },
            }
            teacher_outputs.append(teacher_output)
            teacher_counts[base_record["teacher_id"]] += 1
            task_counts[base_record["teacher_task_id"]] += 1
            records.append(
                {
                    **base_record,
                    "status": "completed",
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    "error": "",
                    "usage": normalized_usage,
                }
            )
        except Exception as exc:
            records.append(
                {
                    **base_record,
                    "status": "failed",
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
            )

    completed = sum(1 for row in records if row.get("status") == "completed")
    failed = sum(1 for row in records if row.get("status") == "failed")
    skipped = sum(1 for row in records if str(row.get("status", "")).startswith("skipped"))
    body = {
        "schema": "teacher_execution_result.v1",
        "created_at": _now(),
        "execution_plan_id": str(execution_plan.get("execution_plan_id", "") or ""),
        "distillation_id": str(execution_plan.get("distillation_id", "") or ""),
        "mode": mode,
        "counts": {
            "requests": len(requests),
            "completed_requests": completed,
            "failed_requests": failed,
            "skipped_requests": skipped,
            "teacher_outputs": len(teacher_outputs),
        },
        "teacher_mix_observed": dict(sorted(teacher_counts.items())),
        "task_mix_observed": dict(sorted(task_counts.items())),
        "request_results": records,
        "teacher_outputs": teacher_outputs,
        "usage": usage_totals,
        "validation": {
            "ok": bool(plan_ok and (mode != "live" or (completed > 0 and failed == 0))),
            "plan_ok": plan_ok,
            "completed_all_live_requests": mode != "live" or (completed == len(requests) and failed == 0),
            "blockers": [],
        },
    }
    body["execution_result_id"] = _stable_id("teacherrun", {k: v for k, v in body.items() if k != "created_at"})
    return body
