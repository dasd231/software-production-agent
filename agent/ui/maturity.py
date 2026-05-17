"""Project maturity assessment for generated product runs.

函数流程图：
    build_maturity_report(files, progress, mode)
      -> _has_any() 检测前端/后端/测试/文档/安全/入口/包文件
      -> rules 累加 score
      -> _level(score, features)
      -> _gaps(features)
      -> _next_steps(features)
      -> 返回可渲染 maturity report

你可以继续练算法/工程化的点：
    1. 评分算法：现在是启发式 checklist；可接测试结果、静态分析、依赖审计和用户验收。
    2. 产品成熟度：可拆成 prototype/readiness/security/maintainability 四个子分。
    3. 行业模板：不同项目类型（后台、CRM、游戏、API）应有不同成熟度权重。
    4. 证据链：每个加分项可以记录具体文件、命令和事件证据，避免“空口评分”。
    5. 迭代建议：可结合用户需求和缺口生成下一轮 agent prompt。
"""

from __future__ import annotations

from typing import Any


def _has_any(files: set[str], patterns: tuple[str, ...]) -> bool:
    return any(any(path == pattern or path.endswith(pattern) or pattern in path for pattern in patterns) for path in files)


def _feature_map(files: set[str], progress: str, mode: str) -> dict[str, bool]:
    return {
        "finished": progress.startswith("finished:") or progress.startswith("run_ok") or "ok" in progress,
        "readme": "README.md" in files,
        "frontend": any(path.startswith("frontend/") or path.startswith("preview/") for path in files),
        "backend": any(path.startswith("backend/") for path in files) or "app.py" in files,
        "package": _has_any(files, ("package.json", "pom.xml", "requirements.txt", "pyproject.toml")),
        "entrypoint": _has_any(
            files,
            (
                "app.py",
                "main.py",
                "frontend/src/App.vue",
                "frontend/index.html",
                "preview/index.html",
                "Application.java",
            ),
        ),
        "tests": any("/test" in path.lower() or path.lower().startswith("tests/") or ".spec." in path for path in files),
        "security": any(path.startswith("security/") for path in files) or "sandbox_manifest.json" in files,
        "preview": "sandbox_manifest.json" in files or any(path.startswith("preview/") for path in files),
        "api_contract": any(path in {"docs/API_CONTRACT.md", "openapi.yaml", "openapi.json"} for path in files),
        "solution_backup": "docs/SOLUTION_BACKUP.md" in files or "solution_manifest.json" in files,
        "llm_mode": mode == "llm",
    }


def _checks(features: dict[str, bool]) -> list[dict[str, Any]]:
    rows = [
        ("需求闭环完成", "finished"),
        ("README / 使用说明", "readme"),
        ("前端入口", "frontend"),
        ("后端或 API 入口", "backend"),
        ("依赖/构建文件", "package"),
        ("可识别主入口", "entrypoint"),
        ("测试文件", "tests"),
        ("安全/沙盒说明", "security"),
        ("可预览窗口", "preview"),
        ("方案备份", "solution_backup"),
    ]
    return [{"label": label, "ok": bool(features.get(key, False))} for label, key in rows]


def _score(features: dict[str, bool]) -> int:
    weights = {
        "finished": 12,
        "readme": 8,
        "frontend": 14,
        "backend": 14,
        "package": 10,
        "entrypoint": 10,
        "tests": 12,
        "security": 8,
        "preview": 8,
        "solution_backup": 4,
        "llm_mode": 4,
    }
    return min(sum(weight for key, weight in weights.items() if features.get(key)), 100)


def _level(score: int, features: dict[str, bool]) -> str:
    if score >= 86 and features.get("tests"):
        return "接近可交付"
    if score >= 70:
        return "可运行脚手架"
    if score >= 52:
        return "可预览原型"
    if score >= 30:
        return "早期原型"
    return "草稿"


def _gaps(features: dict[str, bool]) -> list[str]:
    gaps = []
    if not features.get("preview"):
        gaps.append("缺少可直接体验的前端预览窗口")
    if not features.get("tests"):
        gaps.append("缺少测试文件或验收用例")
    if not features.get("security"):
        gaps.append("缺少安全/沙盒说明")
    if not features.get("backend"):
        gaps.append("缺少后端或 API 入口")
    if not features.get("package"):
        gaps.append("缺少依赖/构建配置")
    if not features.get("solution_backup"):
        gaps.append("缺少可复用方案备份")
    return gaps[:4]


def _next_steps(features: dict[str, bool]) -> list[str]:
    steps = []
    if not features.get("preview"):
        steps.append("生成一个静态沙盒预览，让用户先体验交互")
    if not features.get("tests"):
        steps.append("补最小 smoke test 和关键业务验收用例")
    if not features.get("security"):
        steps.append("补 sandbox/security manifest，明确运行边界")
    if features.get("frontend") and features.get("backend") and not features.get("api_contract"):
        steps.append("补前后端接口契约和 mock 数据")
    if not features.get("solution_backup"):
        steps.append("生成方案备份，后续接入方案检索复用")
    if not steps:
        steps.append("进入真实构建、端到端验收、打包和部署演练")
    return steps[:4]


def build_maturity_report(files: list[str], progress: str, mode: str) -> dict[str, Any]:
    file_set = set(files)
    features = _feature_map(file_set, progress, mode)
    score = _score(features)
    return {
        "score": score,
        "level": _level(score, features),
        "checks": _checks(features),
        "gaps": _gaps(features),
        "next_steps": _next_steps(features),
        "artifact_count": len([path for path in files if not path.startswith(".")]),
    }
