"""Execution feedback helpers to keep loop logic testable and small."""

from __future__ import annotations

import json
from typing import Any
"""
执行反馈分析器
负责将原始动作执行结果转化为精简、结构化、LLM友好的错误反馈。
核心目标是把主循环里的反馈逻辑抽出来，使其可独立测试。
"""
# LLM 的诊断信息
def analyze_exec_result(result: dict[str, Any]) -> str | None:
    error_code = str(result.get("error_code", "") or "")
    if error_code:
        return json.dumps(
            {
                "action": result.get("action"),
                "error_code": error_code,
                "retryable": bool(result.get("retryable", False)),
                "recommended_action": result.get("recommended_action"),
                "error": result.get("error") or result.get("feedback") or result.get("stderr") or "",
            },
            ensure_ascii=False,
        )
    if result.get("action") == "run_command" and not result.get("ok"):
        return result.get("feedback") or result.get("stderr") or "run_command failed"
    if result.get("action") == "production_check" and not result.get("ok"):
        report = result.get("report", {})
        if isinstance(report, dict):
            checks = report.get("checks", [])
            failed = [c for c in checks if isinstance(c, dict) and not c.get("ok", False)] if isinstance(checks, list) else []
            return json.dumps(
                {
                    "action": "production_check",
                    "summary": report.get("summary", {}),
                    "failed_checks": failed[:3],
                },
                ensure_ascii=False,
            )
        return "production_check failed"
    if result.get("action") == "git_init" and not result.get("ok"):
        return result.get("detail") or str(result.get("stderr", "")) or "git_init failed"
    if result.get("action") == "finish":
        return None
    if not result.get("ok", True):
        return json.dumps(result, ensure_ascii=False)
    return None
