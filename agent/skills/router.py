"""Minimal skill router inspired by gstack/ecc skill workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillHint:
    name: str
    reason: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "reason": self.reason, "priority": self.priority}


def suggest_skills(goal: str, plan: dict[str, Any], state_dict: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    text = " ".join(
        [
            str(goal or ""),
            str(plan.get("stage", "")),
            str(plan.get("tasks", "")),
            str(state_dict.get("progress", "")),
        ]
    ).lower()
    hints: list[SkillHint] = []
    if "flask" in text or "api" in text:
        hints.append(SkillHint("python_flask_api", "Goal mentions API/Flask implementation.", 10))
    if "test" in text or "pytest" in text or "selftest" in text:
        hints.append(SkillHint("python_testing_pytest", "Plan includes test/verification tasks.", 9))
    if "error" in text or "fix" in text or "investigate" in text or "traceback" in text:
        hints.append(SkillHint("debug_traceback_triage", "State/plan indicates failure diagnosis.", 10))
    if "ship" in text or "review" in text or "gate" in text:
        hints.append(SkillHint("release_quality_gate", "Plan is in review/ship quality stage.", 8))
    if not hints:
        hints.append(SkillHint("general_coding_loop", "Default coding loop skill.", 1))
    ordered = sorted(hints, key=lambda h: (-h.priority, h.name))
    return [h.to_dict() for h in ordered[: max(1, limit)]]

