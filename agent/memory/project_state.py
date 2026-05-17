"""项目状态（核心）— AIread 结构 + 可恢复字段。

函数流程图：
    ProjectState
      -> to_dict()/from_dict()
      -> save()/load()
      -> sync_file_list(root)
      -> update_from_result(result)
          -> 更新 last_result / counters / progress
      -> record_error()
      -> record_quality()
      -> policy 字段保存策略层状态

你可以继续练算法/工程化的点：
    1. 状态迁移：当前 from_dict 宽容读取旧字段；可以加入 schema migration registry。
    2. PolicyState：当前是 dict；后续可以提升为 DTO，约束 action_values/reward_history。
    3. bandit：当前 action_value_estimates 是本 run 级别；可以抽全局 policy memory 跨项目复用。
    4. 文件同步：当前每轮 rglob；可以做增量索引和 hash 缓存。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ProjectState:
    schema_version: str = "1"
    goal: str = ""
    last_iteration: int = -1
    files: list[str] = field(default_factory=list)
    structure: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    current_stage: str = ""
    progress: str = ""
    quality: dict[str, Any] = field(default_factory=lambda: {"review_score": None, "health_score": None, "wtf_likelihood": 0})
    policy: dict[str, Any] = field(
        default_factory=lambda: {
            "policy_version": "heuristic-v1",
            "recent_strategy": "",
            "last_selected_action": "",
            "last_executed_action": "",
            "last_reward": 0.0,
            "decision_count": 0,
            "reward_total": 0.0,
            "tool_success_stats": {},
            "action_value_estimates": {},
        }
    )
    counters: dict[str, int] = field(
        default_factory=lambda: {"iterations": 0, "fix_attempts": 0, "command_failures": 0, "reverts": 0}
    )
    last_result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProjectState:
        raw_quality = d.get("quality")
        quality = (
            dict(raw_quality)
            if isinstance(raw_quality, dict)
            else {"review_score": None, "health_score": None, "wtf_likelihood": 0}
        )
        raw_policy = d.get("policy")
        policy = (
            dict(raw_policy)
            if isinstance(raw_policy, dict)
            else {
                "policy_version": "heuristic-v1",
                "recent_strategy": "",
                "last_selected_action": "",
                "last_executed_action": "",
                "last_reward": 0.0,
                "decision_count": 0,
                "reward_total": 0.0,
                "tool_success_stats": {},
                "action_value_estimates": {},
            }
        )
        raw_counters = d.get("counters")
        counters = (
            dict(raw_counters)
            if isinstance(raw_counters, dict)
            else {"iterations": 0, "fix_attempts": 0, "command_failures": 0, "reverts": 0}
        )
        raw_files = d.get("files")
        raw_structure = d.get("structure")
        raw_errors = d.get("errors")
        raw_last_result = d.get("last_result")
        return cls(
            schema_version=str(d.get("schema_version", "1")),
            goal=str(d.get("goal", "")),
            last_iteration=int(d.get("last_iteration", -1)),
            files=list(raw_files) if isinstance(raw_files, list) else [],
            structure=dict(raw_structure) if isinstance(raw_structure, dict) else {},
            errors=list(raw_errors) if isinstance(raw_errors, list) else [],
            current_stage=str(d.get("current_stage", "")),
            progress=str(d.get("progress", "")),
            quality=quality,
            policy=policy,
            counters=counters,
            last_result=dict(raw_last_result) if isinstance(raw_last_result, dict) else {},
        )

    def record_error(self, source: str, message: str, stderr: str = "") -> None:
        self.errors.append(
            {
                "source": source,
                "message": message,
                "stderr": stderr,
            }
        )

    def sync_file_list(self, root: Path) -> None:
        if not root.exists():
            self.files = []
            return
        self.files = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())

    def update_from_result(self, result: dict[str, Any]) -> None:
        self.last_result = dict(result)
        self.counters["iterations"] = int(self.counters.get("iterations", 0)) + 1
        if result.get("action") == "run_command":
            if result.get("ok"):
                self.progress = "run_ok"
            else:
                self.progress = "run_failed"
                self.counters["command_failures"] = int(self.counters.get("command_failures", 0)) + 1
        elif result.get("action") == "production_check":
            if result.get("ok"):
                self.progress = "production_check_ok"
            else:
                self.progress = "production_check_failed"
                self.counters["command_failures"] = int(self.counters.get("command_failures", 0)) + 1
        elif result.get("action") == "finish" and result.get("ok"):
            self.progress = "finished:" + str(result.get("reason", "done"))

    def record_quality(self, *, review_score: float | None = None, health_score: float | None = None) -> None:
        if review_score is not None:
            self.quality["review_score"] = round(float(review_score), 2)
        if health_score is not None:
            self.quality["health_score"] = round(float(health_score), 2)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ProjectState:
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
