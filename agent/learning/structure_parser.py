"""Project directory structure parser.

函数流程图：
    parse_structure(repo_path, max_files)
      -> walk repo_path
      -> ignore noisy dirs/files
      -> collect files/directories
      -> infer languages by extension
      -> detect entrypoints/tests/package files
      -> StructureSummary

你可以继续练算法/工程化的点：
    1. 语言识别：现在按扩展名；可接 Linguist 规则和 shebang。
    2. 入口识别：现在是规则；可解析 package/pyproject/pom/main class。
    3. 大仓库采样：现在简单截断；可按目录重要性和文件熵做优先采样。
"""

from __future__ import annotations

from pathlib import Path

from agent.learning.schemas import StructureSummary

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache"}
PACKAGE_FILES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "pom.xml",
    "build.gradle",
    "Cargo.toml",
    "go.mod",
}
EXT_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".md": "markdown",
    ".vue": "vue",
    ".html": "html",
    ".css": "css",
}


def _is_test_path(rel: str) -> bool:
    lower = rel.lower()
    return "/test" in lower or "test_" in lower or lower.endswith("_test.py") or lower.endswith(".spec.ts")


def _is_entrypoint(rel: str) -> bool:
    lower = rel.lower()
    name = Path(rel).name.lower()
    return name in {"app.py", "main.py", "index.js", "main.js", "app.vue", "index.html"} or lower.endswith(
        "application.java"
    )


def parse_structure(repo_path: Path, max_files: int = 500) -> StructureSummary:
    files: list[str] = []
    directories: set[str] = set()
    languages: dict[str, int] = {}
    entrypoints: list[str] = []
    tests: list[str] = []
    package_files: list[str] = []
    ignored_count = 0
    truncated = False
    root = repo_path.resolve()
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS or part.startswith(".agent_") for part in rel_parts):
            ignored_count += 1
            continue
        if path.is_dir():
            directories.add(path.relative_to(root).as_posix())
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if len(files) >= max_files:
            truncated = True
            break
        files.append(rel)
        lang = EXT_LANG.get(path.suffix.lower())
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
        if _is_entrypoint(rel):
            entrypoints.append(rel)
        if _is_test_path(rel):
            tests.append(rel)
        if path.name in PACKAGE_FILES:
            package_files.append(rel)
    return StructureSummary(
        files=files,
        directories=sorted(directories),
        languages=dict(sorted(languages.items())),
        entrypoints=entrypoints,
        tests=tests,
        package_files=package_files,
        ignored_count=ignored_count,
        truncated=truncated,
    )
