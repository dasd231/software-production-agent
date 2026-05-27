from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PatchRisk = Literal["low", "medium", "high"]

_HUNK_RE = re.compile(r"^@@\s+-(?P<old>[^\s]+)\s+\+(?P<new>[^\s]+)\s+@@")
_SYMBOL_RE = re.compile(r"\b(class|def|function|interface|enum|type)\s+([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True, slots=True)
class DiffHunk:
    file_path: str
    header: str
    added_lines: tuple[str, ...] = ()
    removed_lines: tuple[str, ...] = ()
    context_lines: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("added_lines", "removed_lines", "context_lines", "symbols"):
            data[key] = list(data[key])
        return data


@dataclass(frozen=True, slots=True)
class PatchProposal:
    proposal_id: str
    goal: str
    files_changed: tuple[str, ...]
    hunks: tuple[DiffHunk, ...]
    risk_level: PatchRisk
    risk_reasons: tuple[str, ...]
    test_suggestions: tuple[str, ...]
    rollback_strategy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "patch_proposal.v1",
            "proposal_id": self.proposal_id,
            "goal": self.goal,
            "files_changed": list(self.files_changed),
            "hunks": [hunk.to_dict() for hunk in self.hunks],
            "risk_level": self.risk_level,
            "risk_reasons": list(self.risk_reasons),
            "test_suggestions": list(self.test_suggestions),
            "rollback_strategy": self.rollback_strategy,
        }


def _stable_id(goal: str, diff_text: str) -> str:
    return "patch:" + hashlib.sha1((goal + "\n" + diff_text).encode("utf-8", errors="ignore")).hexdigest()[:14]


def _extract_symbols(lines: list[str]) -> tuple[str, ...]:
    symbols: list[str] = []
    for line in lines:
        for match in _SYMBOL_RE.finditer(line):
            symbols.append(match.group(2))
    return tuple(dict.fromkeys(symbols))


def parse_unified_diff(diff_text: str) -> list[DiffHunk]:
    current_file = ""
    current_header = ""
    added: list[str] = []
    removed: list[str] = []
    context: list[str] = []
    hunks: list[DiffHunk] = []

    def flush() -> None:
        nonlocal added, removed, context, current_header
        if current_file and current_header:
            lines = [*added, *removed, *context]
            hunks.append(
                DiffHunk(
                    file_path=current_file,
                    header=current_header,
                    added_lines=tuple(added),
                    removed_lines=tuple(removed),
                    context_lines=tuple(context),
                    symbols=_extract_symbols(lines),
                )
            )
        added, removed, context = [], [], []

    for raw in str(diff_text or "").splitlines():
        line = raw.rstrip("\n")
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+++ ") and not line.startswith("+++"):  # defensive only
            current_file = line[4:]
            continue
        if line.startswith("@@ "):
            flush()
            current_header = line
            continue
        if not current_header:
            continue
        if line.startswith("+") and not line.startswith("+++"):  # added line
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        else:
            context.append(line[1:] if line.startswith(" ") else line)
    flush()
    return hunks


def _risk_for(files: tuple[str, ...], hunks: list[DiffHunk]) -> tuple[PatchRisk, tuple[str, ...]]:
    reasons: list[str] = []
    joined = "\n".join([*(line for h in hunks for line in h.added_lines), *(line for h in hunks for line in h.removed_lines)]).lower()
    if any(path.endswith(('.sql', '.yaml', '.yml')) or 'migration' in path.lower() for path in files):
        reasons.append("schema_or_infra_file_changed")
    if any(term in joined for term in ("password", "secret", "token", "private_key")):
        reasons.append("secret_sensitive_change")
    if any(term in joined for term in ("delete", "drop table", "rm -rf", "truncate")):
        reasons.append("destructive_operation")
    if any("auth" in path.lower() or "security" in path.lower() for path in files):
        reasons.append("auth_or_security_surface_changed")
    if sum(len(h.added_lines) + len(h.removed_lines) for h in hunks) > 120:
        reasons.append("large_patch")
    if any(reason in reasons for reason in ("secret_sensitive_change", "destructive_operation", "auth_or_security_surface_changed")):
        return "high", tuple(reasons)
    if reasons:
        return "medium", tuple(reasons)
    return "low", tuple(reasons)


def build_patch_proposal(goal: str, diff_text: str) -> PatchProposal:
    hunks = parse_unified_diff(diff_text)
    files = tuple(dict.fromkeys(h.file_path for h in hunks if h.file_path))
    risk, reasons = _risk_for(files, hunks)
    tests: list[str] = []
    if any("test" in path.lower() for path in files):
        tests.append("run touched test files directly")
    if any(path.endswith(".py") for path in files):
        tests.append("python -m pytest relevant tests")
    if any(path.endswith((".ts", ".tsx", ".js")) for path in files):
        tests.append("npm test / typecheck for touched frontend package")
    if any("auth" in path.lower() or "security" in path.lower() for path in files):
        tests.append("auth/RBAC regression and negative permission tests")
    if not tests:
        tests.append("run smoke tests for touched module")
    rollback = "git apply -R original.patch or revert commit; for migrations use explicit down/compensation script"
    return PatchProposal(
        proposal_id=_stable_id(goal, diff_text),
        goal=goal,
        files_changed=files,
        hunks=tuple(hunks),
        risk_level=risk,
        risk_reasons=reasons,
        test_suggestions=tuple(dict.fromkeys(tests)),
        rollback_strategy=rollback,
    )


def patch_proposal_to_mermaid(proposal: PatchProposal) -> str:
    lines = ["flowchart TD", f"    goal[\"Goal: {proposal.goal[:80]}\"]", f"    patch[\"{proposal.proposal_id} / risk={proposal.risk_level}\"]", "    goal --> patch"]
    for idx, file in enumerate(proposal.files_changed):
        fid = f"file{idx}"
        lines.append(f"    {fid}[\"File: {file}\"]")
        lines.append(f"    patch --> {fid}")
    for idx, hunk in enumerate(proposal.hunks):
        hid = f"hunk{idx}"
        lines.append(f"    {hid}[\"Hunk: +{len(hunk.added_lines)} -{len(hunk.removed_lines)}\"]")
        file_idx = list(proposal.files_changed).index(hunk.file_path) if hunk.file_path in proposal.files_changed else 0
        lines.append(f"    file{file_idx} --> {hid}")
    return "\n".join(lines) + "\n"
