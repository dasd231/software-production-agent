"""GitHub project searcher.

函数流程图：
    GitHubSearchClient.search(query, per_page)
      -> build search/repositories URL
      -> optional GITHUB_TOKEN header
      -> urllib.request.urlopen()
      -> json.loads()
      -> _repo_from_github_item()
      -> list[RepoCandidate]

你可以继续练算法/工程化的点：
    1. 搜索排序：现在依赖 GitHub stars；可引入 freshness/license/topic 多目标排序。
    2. 速率限制：现在只抛错；可读取 rate-limit headers 做退避和缓存。
    3. 查询扩展：可用 WebSearch/LLM 把用户 query 扩成 topic/language/license 组合。
    4. 去重策略：可按 owner/name、fork/source、README embedding 做去重。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Callable

from agent.learning.schemas import RepoCandidate

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
USER_AGENT = "software-production-agent-learning/0.1"


class GitHubSearchError(RuntimeError):
    pass


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _repo_from_github_item(item: dict) -> RepoCandidate:
    license_obj = item.get("license") if isinstance(item.get("license"), dict) else {}
    topics = item.get("topics") if isinstance(item.get("topics"), list) else []
    return RepoCandidate(
        full_name=str(item.get("full_name", "")),
        html_url=str(item.get("html_url", "")),
        clone_url=str(item.get("clone_url", "")),
        description=str(item.get("description") or ""),
        stargazers_count=_safe_int(item.get("stargazers_count")),
        license_spdx=str(license_obj.get("spdx_id") or ""),
        pushed_at=str(item.get("pushed_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
        default_branch=str(item.get("default_branch") or "main"),
        topics=tuple(str(x) for x in topics),
    )


class GitHubSearchClient:
    def __init__(
        self,
        token: str | None = None,
        opener: Callable | None = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self.opener = opener or urllib.request.urlopen

    def search(self, query: str, per_page: int = 10) -> list[RepoCandidate]:
        query = query.strip()
        if not query:
            return []
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": str(max(1, min(int(per_page), 100))),
        }
        url = GITHUB_SEARCH_URL + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        try:
            with self.opener(request, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            raise GitHubSearchError(str(exc)) from exc
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        return [_repo_from_github_item(x) for x in items if isinstance(x, dict)]


def search_github_projects(query: str, top_k: int = 10, token: str | None = None) -> list[RepoCandidate]:
    return GitHubSearchClient(token=token).search(query, per_page=top_k)
