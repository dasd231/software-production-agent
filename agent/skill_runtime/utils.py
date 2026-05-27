from __future__ import annotations

import re
from collections.abc import Iterable

_WORD_RE = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(str(text or "")) if len(m.group(0).strip()) >= 2}


def unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def overlap_score(a: str | Iterable[str], b: str | Iterable[str]) -> float:
    a_text = " ".join(a) if not isinstance(a, str) else a
    b_text = " ".join(b) if not isinstance(b, str) else b
    left = tokenize(a_text)
    right = tokenize(b_text)
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left | right), 1)


def contains_any(text: str, terms: Iterable[str]) -> bool:
    lower = str(text or "").lower()
    return any(str(term).lower() in lower for term in terms if str(term).strip())
