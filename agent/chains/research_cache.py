"""Conservative two-level cache for local extractive research results."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, cast

from agent.chains.research_types import ResearchCachePayload


CACHE_SCHEMA = "research_cache_entry.v1"
CACHE_POLICY = "local_extractive_only"
CACHE_VERSION = "v1"
L1_TTL_SECONDS = 60
DEFAULT_L2_TTL_SECONDS = 24 * 60 * 60

_L1_CACHE: dict[str, tuple[float, ResearchCachePayload]] = {}


def is_cache_eligible(*, use_cache: bool, use_web: bool, use_llm: bool) -> bool:
    return bool(use_cache) and not bool(use_web) and not bool(use_llm)


def _resolved_strings(paths: tuple[Path, ...]) -> list[str]:
    out: list[str] = []
    for path in paths:
        try:
            out.append(str(path.resolve()))
        except OSError:
            out.append(str(path))
    return out


def build_cache_key(
    *,
    query: str,
    workspace: Path,
    solution_dirs: tuple[Path, ...],
    learning_dirs: tuple[str, ...],
    top_k: int,
) -> str:
    payload = {
        "version": CACHE_VERSION,
        "policy": CACHE_POLICY,
        "query": query,
        "workspace": str(workspace.resolve()),
        "solution_dirs": _resolved_strings(solution_dirs),
        "learning_dirs": [str(x) for x in learning_dirs],
        "top_k": int(top_k),
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.blake2b(body.encode("utf-8"), digest_size=16).hexdigest()


def _cache_path(workspace: Path, key: str) -> Path:
    return workspace / ".agent_cache" / "research" / f"{key}.json"


def _valid_payload(raw: Any) -> ResearchCachePayload | None:
    if not isinstance(raw, dict):
        return None
    required = ("answer", "solution_hits", "rag_hints", "rag_summary", "web_results", "evidence_policy", "llm_trace")
    if not all(key in raw for key in required):
        return None
    if not isinstance(raw.get("answer"), str):
        return None
    for key in ("solution_hits", "rag_hints", "web_results"):
        if not isinstance(raw.get(key), list):
            return None
    for key in ("rag_summary", "evidence_policy", "llm_trace"):
        if not isinstance(raw.get(key), dict):
            return None
    return cast(ResearchCachePayload, raw)


def load_cached_payload(
    workspace: Path,
    *,
    key: str,
    ttl_seconds: int,
    refresh: bool = False,
    now: float | None = None,
) -> tuple[ResearchCachePayload | None, dict[str, Any]]:
    now_ts = time.time() if now is None else float(now)
    ttl = max(int(ttl_seconds), 1)
    if refresh:
        return None, {
            "status": "refresh_requested",
            "layer": "",
            "policy": CACHE_POLICY,
            "ttl_seconds": ttl,
            "key": key,
        }
    l1 = _L1_CACHE.get(key)
    if l1:
        created_at, payload = l1
        age = max(now_ts - created_at, 0.0)
        if age <= min(ttl, L1_TTL_SECONDS):
            return payload, {
                "status": "hit",
                "layer": "L1",
                "policy": CACHE_POLICY,
                "ttl_seconds": ttl,
                "age_seconds": round(age, 3),
                "key": key,
            }
        _L1_CACHE.pop(key, None)
    path = _cache_path(workspace, key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, {
            "status": "miss",
            "layer": "",
            "policy": CACHE_POLICY,
            "ttl_seconds": ttl,
            "key": key,
        }
    if not isinstance(raw, dict) or raw.get("schema") != CACHE_SCHEMA:
        return None, {
            "status": "invalid",
            "layer": "L2",
            "policy": CACHE_POLICY,
            "ttl_seconds": ttl,
            "key": key,
        }
    try:
        created_at = float(raw.get("created_at_epoch"))
    except (TypeError, ValueError):
        return None, {
            "status": "invalid",
            "layer": "L2",
            "policy": CACHE_POLICY,
            "ttl_seconds": ttl,
            "key": key,
        }
    age = max(now_ts - created_at, 0.0)
    if age > ttl:
        return None, {
            "status": "expired",
            "layer": "L2",
            "policy": CACHE_POLICY,
            "ttl_seconds": ttl,
            "age_seconds": round(age, 3),
            "key": key,
        }
    payload = _valid_payload(raw.get("payload"))
    if payload is None:
        return None, {
            "status": "invalid",
            "layer": "L2",
            "policy": CACHE_POLICY,
            "ttl_seconds": ttl,
            "key": key,
        }
    _L1_CACHE[key] = (created_at, payload)
    return payload, {
        "status": "hit",
        "layer": "L2",
        "policy": CACHE_POLICY,
        "ttl_seconds": ttl,
        "age_seconds": round(age, 3),
        "key": key,
    }


def store_cached_payload(
    workspace: Path,
    *,
    key: str,
    payload: ResearchCachePayload,
    now: float | None = None,
) -> Path:
    now_ts = time.time() if now is None else float(now)
    _L1_CACHE[key] = (now_ts, payload)
    path = _cache_path(workspace, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": CACHE_SCHEMA,
                "policy": CACHE_POLICY,
                "created_at_epoch": now_ts,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def clear_l1_cache() -> None:
    _L1_CACHE.clear()
