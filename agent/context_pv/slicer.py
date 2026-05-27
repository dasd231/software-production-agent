from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from agent.context_pv.schema import ContextPVPolicy, ContextSlice


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z_][A-Za-z0-9_]*|\d+|```|#{1,6}|[^\s]", re.UNICODE)


@dataclass(slots=True)
class _Block:
    text: str
    label: str
    tokens: int


@dataclass(slots=True)
class _RawSlice:
    text: str
    label: str
    start: int
    end: int


def estimate_tokens(text: str) -> int:
    """Fast deterministic token estimate.

    It is deliberately dependency-free. In production this can be swapped with
    the target model tokenizer while keeping the same slicing contract.
    """

    if not text:
        return 0
    return len(_TOKEN_RE.findall(text))


def _window_by_tokens(text: str, limit: int, *, tail: bool) -> str:
    if limit <= 0 or not text:
        return ""
    matches = list(_TOKEN_RE.finditer(text))
    if len(matches) <= limit:
        return text
    if tail:
        return text[matches[-limit].start() :]
    return text[: matches[limit - 1].end()]


def _checksum(text: str, *, version: str, ordinal: int) -> str:
    return hashlib.sha256(f"{version}:{ordinal}\n{text}".encode("utf-8")).hexdigest()


def semantic_label(text: str) -> str:
    sample = text.strip()
    low = sample.lower()
    if not sample:
        return "empty"
    if sample.startswith("```") or re.search(r"^\s*(def|class|import|from|function|const|let|var)\b", sample, re.M):
        return "code"
    if re.match(r"^#{1,6}\s+\S+", sample):
        return "heading"
    if any(word in low for word in ("summary", "overview", "abstract", "tl;dr", "摘要", "概述")):
        return "summary"
    lines = [line for line in sample.splitlines() if line.strip()]
    if len(lines) >= 2 and sum(1 for line in lines if "|" in line) >= 2:
        return "table"
    if lines and sum(1 for line in lines if re.match(r"^\s*(-|\*|\d+[.)])\s+", line)) >= max(1, len(lines) // 2):
        return "list"
    return "prose"


def _split_semantic_blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    current: list[str] = []
    in_code = False

    def flush() -> None:
        nonlocal current
        joined = "\n".join(current).strip("\n")
        current = []
        if joined.strip():
            blocks.append(_Block(joined, semantic_label(joined), estimate_tokens(joined)))

    for line in text.splitlines():
        stripped = line.strip()
        is_fence = stripped.startswith("```")
        if is_fence:
            if current and not in_code:
                flush()
            current.append(line)
            in_code = not in_code
            if not in_code:
                flush()
            continue
        if in_code:
            current.append(line)
            continue
        if re.match(r"^#{1,6}\s+\S+", stripped):
            flush()
            current.append(line)
            flush()
            continue
        if not stripped:
            flush()
            continue
        current.append(line)
    flush()
    return blocks


def _split_oversized_block(block: _Block, max_tokens: int) -> list[_Block]:
    if block.tokens <= max_tokens:
        return [block]
    if block.label == "code":
        units = block.text.splitlines()
        joiner = "\n"
    else:
        # Sentence-ish splitting for prose, falling back to lines for Markdown.
        units = [x for x in re.split(r"(?<=[。！？.!?])\s+|\n+", block.text) if x.strip()]
        joiner = "\n"
    out: list[_Block] = []
    cur: list[str] = []
    cur_tokens = 0
    for unit in units:
        unit_tokens = max(1, estimate_tokens(unit))
        if cur and cur_tokens + unit_tokens > max_tokens:
            joined = joiner.join(cur)
            out.append(_Block(joined, block.label, estimate_tokens(joined)))
            cur = []
            cur_tokens = 0
        if unit_tokens > max_tokens:
            words = unit.split()
            if len(words) <= 1:
                step = max(1, len(unit) // max(1, unit_tokens // max_tokens + 1))
                chunks = [unit[i : i + step] for i in range(0, len(unit), step)]
            else:
                chunks = []
                part: list[str] = []
                part_tokens = 0
                for word in words:
                    word_tokens = max(1, estimate_tokens(word))
                    if part and part_tokens + word_tokens > max_tokens:
                        chunks.append(" ".join(part))
                        part = []
                        part_tokens = 0
                    part.append(word)
                    part_tokens += word_tokens
                if part:
                    chunks.append(" ".join(part))
            for chunk in chunks:
                out.append(_Block(chunk, block.label, estimate_tokens(chunk)))
            continue
        cur.append(unit)
        cur_tokens += unit_tokens
    if cur:
        joined = joiner.join(cur)
        out.append(_Block(joined, block.label, estimate_tokens(joined)))
    return out


def _dominant_label(blocks: list[_Block], *, ordinal: int) -> str:
    labels = [block.label for block in blocks if block.label != "empty"]
    if not labels:
        return "empty"
    if ordinal == 0 and ("summary" in labels or "heading" in labels):
        return "summary"
    for preferred in ("code", "table", "list", "summary", "heading"):
        if preferred in labels:
            return preferred
    return labels[0]


def _build_raw_slices(text: str, policy: ContextPVPolicy) -> tuple[list[_RawSlice], int]:
    total_tokens = estimate_tokens(text)
    if total_tokens <= policy.single_pv_token_threshold:
        return [_RawSlice(text.strip("\n"), semantic_label(text), 0, total_tokens)], total_tokens

    blocks: list[_Block] = []
    for block in _split_semantic_blocks(text):
        blocks.extend(_split_oversized_block(block, policy.max_slice_tokens))
    if not blocks:
        return [_RawSlice("", "empty", 0, 0)], 0

    raw: list[_RawSlice] = []
    cur: list[_Block] = []
    cur_tokens = 0
    cursor = 0

    def emit() -> None:
        nonlocal cur, cur_tokens, cursor
        if not cur:
            return
        ordinal = len(raw)
        joined = "\n\n".join(block.text for block in cur).strip("\n")
        token_count = estimate_tokens(joined)
        raw.append(_RawSlice(joined, _dominant_label(cur, ordinal=ordinal), cursor, cursor + token_count))
        cursor += token_count
        cur = []
        cur_tokens = 0

    for block in blocks:
        if cur and cur_tokens + block.tokens > policy.max_slice_tokens:
            emit()
        cur.append(block)
        cur_tokens += block.tokens
        if cur_tokens >= policy.target_slice_tokens:
            emit()
    emit()
    return raw, total_tokens


def slice_context_text(
    text: str,
    *,
    policy: ContextPVPolicy | None = None,
    version: str = "v1",
    manifest_id: str = "",
) -> tuple[list[ContextSlice], int]:
    active_policy = (policy or ContextPVPolicy()).normalized()
    raw, total_tokens = _build_raw_slices(text, active_policy)
    slices: list[ContextSlice] = []
    for idx, item in enumerate(raw):
        left = _window_by_tokens(raw[idx - 1].text, active_policy.overlap_tokens, tail=True) if idx > 0 else ""
        right = _window_by_tokens(raw[idx + 1].text, active_policy.overlap_tokens, tail=False) if idx + 1 < len(raw) else ""
        left_tokens = estimate_tokens(left)
        right_tokens = estimate_tokens(right)
        slice_text = "\n".join(part for part in (left, item.text, right) if part)
        slice_id = hashlib.sha1(f"{manifest_id}:{version}:{idx}:{item.start}:{item.end}".encode("utf-8")).hexdigest()[:16]
        critical = idx in (0, len(raw) - 1) or item.label in active_policy.critical_labels
        slices.append(
            ContextSlice(
                slice_id=f"ctx-{idx:05d}-{slice_id}",
                ordinal=idx,
                text=slice_text,
                token_start=max(0, item.start - left_tokens),
                token_end=item.end + right_tokens,
                overlap_left=left_tokens,
                overlap_right=right_tokens,
                semantic_label=item.label,
                checksum=_checksum(slice_text, version=version, ordinal=idx),
                version=version,
                critical=critical,
                byte_length=len(slice_text.encode("utf-8")),
            )
        )
    return slices, total_tokens

