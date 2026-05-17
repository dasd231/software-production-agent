"""会话记忆 — 主控侧 transcript + 可选 jsonl 落盘（可审计）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionMemory:
    """环形语义：保留最近 N 条结构化事件供 Brain 组装 prompt。"""

    max_events: int = 120
    events: list[dict[str, Any]] = field(default_factory=list)

    def append(self, role: str, content: str, meta: dict[str, Any] | None = None) -> None:
        item: dict[str, Any] = {"role": role, "content": content}
        if meta:
            item["meta"] = meta
        self.events.append(item)
        overflow = len(self.events) - self.max_events
        if overflow > 0:
            self.events = self.events[overflow:]

    def transcript_for_prompt(self, last: int = 40) -> str:
        lines: list[str] = []
        for e in self.events[-last:]:
            role = e.get("role", "")
            content = e.get("content", "")
            meta = e.get("meta")
            suf = f" {meta}" if meta else ""
            lines.append(f"[{role}]{suf}\n{content}\n")
        return "\n".join(lines)

    def append_jsonl(self, path: Path) -> None:
        """把当前尾部事件增量写入 jsonl（每行一条）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for e in self.events[-20:]:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
