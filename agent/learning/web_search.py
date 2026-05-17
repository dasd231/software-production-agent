"""Web Search supplemental learning.

函数流程图：
    search_web(query, top_k, provider)
      -> provider == duckduckgo ?
           -> DuckDuckGo Instant Answer API
           -> parse AbstractURL/RelatedTopics
         else
           -> fallback_search_links()
      -> list[SearchResult]

你可以继续练算法/工程化的点：
    1. Provider 抽象：现在是无 key DuckDuckGo IA；可接 Tavily/Brave/Bing/自建搜索。
    2. 内容抓取：现在只拿 title/url/snippet；可接网页抓取、正文抽取和可信源评分。
    3. 新鲜度：可按 publish date、domain trust、query intent 做排序。
    4. 与 RAG 融合：web results 可切片入临时向量库，或作为 answer evidence。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Callable

from agent.learning.schemas import SearchResult


def fallback_search_links(query: str, top_k: int = 3) -> list[SearchResult]:
    q = urllib.parse.quote_plus(query.strip())
    if not q:
        return []
    links = [
        ("GitHub Search", f"https://github.com/search?q={q}&type=repositories"),
        ("Web Search", f"https://duckduckgo.com/?q={q}"),
        ("Docs Search", f"https://www.google.com/search?q={q}+documentation"),
    ]
    return [
        SearchResult(title=title, url=url, snippet="Fallback search link; fetch provider unavailable.", source="fallback")
        for title, url in links[: max(int(top_k), 0)]
    ]


def _flatten_related(items: list[object]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "Topics" in item and isinstance(item["Topics"], list):
            out.extend(_flatten_related(item["Topics"]))
        else:
            out.append(item)
    return out


def search_web(
    query: str,
    top_k: int = 5,
    *,
    provider: str = "duckduckgo",
    opener: Callable | None = None,
) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []
    if provider != "duckduckgo":
        return fallback_search_links(query, top_k=top_k)
    opener = opener or urllib.request.urlopen
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    request = urllib.request.Request(url, headers={"User-Agent": "software-production-agent-learning/0.1"})
    try:
        with opener(request, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return fallback_search_links(query, top_k=top_k)
    results: list[SearchResult] = []
    abstract_url = str(payload.get("AbstractURL") or "")
    if abstract_url:
        results.append(
            SearchResult(
                title=str(payload.get("Heading") or query),
                url=abstract_url,
                snippet=str(payload.get("AbstractText") or "")[:500],
                source="duckduckgo",
            )
        )
    related = payload.get("RelatedTopics") if isinstance(payload.get("RelatedTopics"), list) else []
    for item in _flatten_related(related):
        first_url = str(item.get("FirstURL") or "")
        text = str(item.get("Text") or "")
        if not first_url or not text:
            continue
        title = text.split(" - ", 1)[0][:120]
        results.append(SearchResult(title=title, url=first_url, snippet=text[:500], source="duckduckgo"))
        if len(results) >= top_k:
            break
    return results[: max(int(top_k), 0)] or fallback_search_links(query, top_k=top_k)
