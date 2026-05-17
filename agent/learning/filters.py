"""License / Star / 更新时间 filter for repository candidates.

函数流程图：
    filter_repositories(candidates, min_stars, allowed_licenses, updated_after)
      -> _parse_datetime()
      -> stars >= min_stars
      -> license in allowed_licenses if provided
      -> pushed_at/updated_at >= updated_after if provided
      -> sort by stars desc + updated_at desc
      -> max_count 截断

你可以继续练算法/工程化的点：
    1. 许可兼容：现在只按 SPDX 字符串；可接 license compatibility matrix。
    2. 活跃度评分：可综合 pushed_at、issues、PR、release、maintainer 数。
    3. 质量分：可把 README 完整度、测试目录、CI 配置纳入排序。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from agent.learning.schemas import RepoCandidate


def _parse_datetime(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _fresh_enough(candidate: RepoCandidate, threshold: datetime | None) -> bool:
    if threshold is None:
        return True
    actual = _parse_datetime(candidate.pushed_at) or _parse_datetime(candidate.updated_at)
    if actual is None:
        return False
    if actual.tzinfo is None and threshold.tzinfo is not None:
        actual = actual.replace(tzinfo=timezone.utc)
    if threshold.tzinfo is None and actual.tzinfo is not None:
        threshold = threshold.replace(tzinfo=actual.tzinfo)
    return actual >= threshold


def filter_repositories(
    candidates: Iterable[RepoCandidate],
    *,
    min_stars: int = 0,
    allowed_licenses: Iterable[str] | None = None,
    updated_after: str = "",
    max_count: int | None = None,
) -> list[RepoCandidate]:
    allowed = {x.strip().lower() for x in (allowed_licenses or []) if x.strip()}
    threshold = _parse_datetime(updated_after)
    out = []
    for candidate in candidates:
        if candidate.stargazers_count < int(min_stars):
            continue
        if allowed and candidate.license_spdx.strip().lower() not in allowed:
            continue
        if not _fresh_enough(candidate, threshold):
            continue
        out.append(candidate)
    out.sort(key=lambda x: (x.stargazers_count, x.updated_at, x.pushed_at), reverse=True)
    if max_count is not None:
        out = out[: max(int(max_count), 0)]
    return out
