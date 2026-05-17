"""命令策略：内置黑名单 + default.json + 可选外置 JSON 合并。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_BUILTIN: frozenset[str] = frozenset(
    {
        "rm -rf /",
        "rm -rf /*",
        "mkfs.",
        "dd if=",
        ":(){ :|:& };:",
        "cipher /w",
    }
)


def _policy_file_in_package() -> Path:
    return Path(__file__).resolve().parent / "default.json"


def _load_substrings_from_json(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("forbidden_substrings", [])
    if not isinstance(raw, list):
        return frozenset()
    out: set[str] = set()
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.add(x.strip().lower())
    return frozenset(out)


@lru_cache(maxsize=16)
def merged_forbidden_substrings(extra_policy_key: str) -> frozenset[str]:
    """extra_policy_key 为额外策略文件绝对路径，或空串表示无。"""
    base = set(_BUILTIN)
    base.update(_load_substrings_from_json(_policy_file_in_package()))
    if extra_policy_key.strip():
        base.update(_load_substrings_from_json(Path(extra_policy_key)))
    return frozenset(base)


class CommandPolicyError(RuntimeError):
    """由执行器转换为 ExecutorError，避免 policies ↔ executor 循环依赖。"""


def assert_command_policy(cmd: str, extra_policy_path: Path | None = None) -> None:
    key = str(extra_policy_path.resolve()) if extra_policy_path else ""
    frags = merged_forbidden_substrings(key)
    low = cmd.lower()
    for frag in frags:
        if frag in low:
            raise CommandPolicyError(f"command blocked by policy (matched: {frag!r})")
