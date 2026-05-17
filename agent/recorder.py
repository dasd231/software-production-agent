"""结构化事件流 — 与 session transcript 互补（便于外部分析 / 回放）。

函数流程图：
    append_event(path, kind, payload)
      -> path 为 None 时直接返回
      -> build_event_row(kind, payload)
          -> 复制 payload，避免调用方对象被修改
          -> 补 ts/kind/schema_version/event_id
      -> json.dumps(..., default=_json_default)
          -> Path 转 str
          -> set/frozenset 转稳定列表
          -> bytes 转 utf-8/replace 字符串
          -> 其他未知对象转 str
      -> 追加写入 JSONL
      -> strict=False 时吞掉事件写入异常，避免观测失败影响主流程

你可以继续练算法/工程化的点：
    1. event_id：现在用时间 + kind + uuid 做 SHA1 短 ID；可以改成 ULID，天然按时间排序。
    2. run_id：现在由 agent_loop 注入整轮运行 ID；可以进一步加入 parent_run_id 支持恢复链路。
    3. 顺序性：现在没有全局 sequence；可以在 agent_loop 注入单调递增 sequence。
    4. 可靠性：现在是直接追加文件；可以扩展为缓冲队列、批量 flush、失败重试。
    5. Schema：现在是宽松 payload；可以为关键 kind 引入 DTO 校验和版本迁移。
    6. 采样：高频事件未来可做采样/限流，避免超大 JSONL 拖慢本地循环。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(str(x) for x in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _event_id(kind: str, ts: float) -> str:
    token = f"{ts:.9f}:{kind}:{uuid.uuid4().hex}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]


def build_run_id(seed: str = "") -> str:
    token = f"{time.time():.9f}:{seed}:{uuid.uuid4().hex}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]


def build_event_row(
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    ts: float | None = None,
    event_id: str = "",
) -> dict[str, Any]:
    event_ts = time.time() if ts is None else max(0.0, float(ts))
    row = dict(payload or {})
    row.update(
        {
            "ts": event_ts,
            "kind": str(kind),
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id or _event_id(str(kind), event_ts),
        }
    )
    return row


def append_event(path: Path | None, kind: str, payload: dict[str, Any], *, strict: bool = False) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = build_event_row(kind, payload)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
    except (OSError, TypeError, ValueError):
        if strict:
            raise
