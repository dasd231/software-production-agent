"""MCP-like adapter surface for future external tool integration.

函数流程图：
    default_mcp_capabilities()
      -> 从 MCP_TOOL_REGISTRY 返回当前支持的 MCP-like 工具目录与 args_schema

    invoke_mcp_tool(workspace, tool_name, args)
      -> workspace.resolve()
      -> 校验 args 是 dict
      -> MCP_TOOL_REGISTRY 查找 handler
      -> handler 按 tool_name 分发：
           workspace.search -> _safe_int(top_k) -> retrieve_snippets()
           workspace.read   -> file_tools.read_file()
           workspace.list   -> file_tools.list_files()
           workspace.verify -> _safe_bool(include_pytest) + _safe_timeout() -> run_production_checks()
           git.status       -> git_tools.git_status()
           unknown          -> ok=false
      -> 参数异常返回结构化错误，不把异常扩散到主循环

你可以继续练算法/工程化的点：
    1. 工具注册：现在是静态 registry；可以扩展成插件发现、懒加载和权限分组。
    2. 参数 schema：现在是轻量转换；可以做每个工具独立 schema 和默认值策略。
    3. 工具选择：capabilities 现在静态返回；可以按 workspace/阶段/失败类型动态排序。
    4. 搜索策略：workspace.search 直接调用 RAG；可以加 query rewrite、rerank、去重。
    5. 外部 MCP：未来可把 handler 替换成真实 MCP client，并保留同样的返回契约。
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.rag.local_index import retrieve_snippets
from agent.runtime.production_check import run_production_checks
from agent.tools import file_tools, git_tools


McpHandler = Callable[[Path, str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class McpToolSpec:
    name: str
    tool: str
    desc: str
    args_schema: dict[str, Any]
    handler: McpHandler


def _error(tool_name: str, message: str) -> dict[str, Any]:
    return {"ok": False, "tool": tool_name, "error": message}


def _safe_int(value: Any, *, default: int, min_value: int, max_value: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        out = default
    return max(min_value, min(out, max_value))


def _safe_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    return default


def _safe_timeout(value: Any, *, default: float = 120.0, max_value: float = 600.0) -> float:
    try:
        out = default if value is None else float(value)
    except (TypeError, ValueError) as e:
        raise ValueError("timeout must be number") from e
    if not math.isfinite(out):
        raise ValueError("timeout must be finite")
    if out <= 0:
        raise ValueError("timeout must be positive")
    return min(out, max_value)


def _workspace_search(ws: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", ""))
    top_k = _safe_int(args.get("top_k", 3), default=3, min_value=1, max_value=10)
    return {
        "ok": True,
        "tool": tool_name,
        "results": retrieve_snippets(ws, query, top_k=top_k),
    }


def _workspace_read(ws: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path", ""))
    return {"ok": True, "tool": tool_name, "content": file_tools.read_file(ws, path)}


def _workspace_list(ws: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    pattern = str(args.get("pattern", "**/*"))
    return {"ok": True, "tool": tool_name, "files": file_tools.list_files(ws, pattern)}


def _workspace_verify(ws: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    include_pytest = _safe_bool(args.get("include_pytest", True), default=True)
    timeout = _safe_timeout(args.get("timeout"), default=120.0, max_value=600.0)
    return {
        "ok": True,
        "tool": tool_name,
        "report": run_production_checks(ws, include_pytest=include_pytest, timeout=timeout),
    }


def _git_status(ws: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tool": tool_name, "content": git_tools.git_status(ws)}


MCP_TOOL_REGISTRY: dict[str, McpToolSpec] = {
    "workspace.search": McpToolSpec(
        name="workspace.search",
        tool="workspace.search",
        desc="Search local workspace snippets by query.",
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
            },
        },
        handler=_workspace_search,
    ),
    "workspace.read": McpToolSpec(
        name="workspace.read",
        tool="workspace.read",
        desc="Read a file from workspace.",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": ""}},
        },
        handler=_workspace_read,
    ),
    "workspace.list": McpToolSpec(
        name="workspace.list",
        tool="workspace.list",
        desc="List files in workspace.",
        args_schema={
            "type": "object",
            "properties": {"pattern": {"type": "string", "default": "**/*"}},
        },
        handler=_workspace_list,
    ),
    "workspace.verify": McpToolSpec(
        name="workspace.verify",
        tool="workspace.verify",
        desc="Run local production checks for the workspace.",
        args_schema={
            "type": "object",
            "properties": {
                "include_pytest": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 120.0, "minimum": 1.0, "maximum": 600.0},
            },
        },
        handler=_workspace_verify,
    ),
    "git.status": McpToolSpec(
        name="git.status",
        tool="git.status",
        desc="Show git status in porcelain format.",
        args_schema={"type": "object", "properties": {}},
        handler=_git_status,
    ),
}


def default_mcp_capabilities() -> list[dict[str, Any]]:
    return [
        {"name": spec.name, "tool": spec.tool, "desc": spec.desc, "args_schema": deepcopy(spec.args_schema)}
        for spec in MCP_TOOL_REGISTRY.values()
    ]


def invoke_mcp_tool(workspace: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    ws = workspace.resolve()
    if not isinstance(args, dict):
        return _error(tool_name, "args must be object")
    spec = MCP_TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return _error(tool_name, f"unsupported tool: {tool_name}")
    try:
        return spec.handler(ws, tool_name, args)
    except (OSError, ValueError) as e:
        return _error(tool_name, str(e))
