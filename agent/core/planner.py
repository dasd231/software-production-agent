"""Planner：动态阶段建议器 — 启发式默认 + 可选 LLM（仍非固定 DAG）。

函数流程图：
    plan(goal, state, prompts_dir, config)
      -> config.planner_use_llm ?
           -> plan_with_openai()
             -> resolve_llm_provider(config.llm_provider, config.planner_model)
             -> create_openai_compatible_client()
             -> chat.completions.create(response_format=json_object)
             -> _coerce_stage()
           -> 失败时回退 plan_heuristic()
         : -> plan_heuristic()
      -> DynamicStage.to_dict()

    plan_heuristic()
      -> state.errors / command_failures
      -> fixing 或 investigate
      -> current_stage review/qa
      -> qa/ship
      -> 空工作区 coding
      -> run_ok review
      -> 默认 coding

你可以继续练算法/工程化的点：
    1. 阶段策略：现在是规则优先；可做 stage transition scorer。
    2. Planner/Brain 边界：Planner 只建议阶段和任务，不直接决定执行 action。
    3. 多模型规划：轻模型做 stage，大模型做 action，可按任务复杂度动态切换。
    4. 失败回退：现在 LLM planner 异常回退启发式；可记录失败类型并反馈 provider policy。
    5. 上下文特征：可以把 RAG/MCP/skill 命中转成可学习的阶段选择特征。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agent.config import AppConfig
from agent.context.digest import build_context_digest
from agent.llm.providers import create_openai_compatible_client, resolve_llm_provider
from agent.memory.project_state import ProjectState
from agent.pipeline.stages import DynamicStage, StageId, default_stage_catalog

_LOG = logging.getLogger("agent.production.planner")

_PLANNER_LLM_RULES = """You output ONE JSON object only (no markdown).
Keys: "stage" (string), "tasks" (array of strings), "meta" (object).
"stage" MUST be exactly one of: planning, design, coding, testing, fixing, review, qa, ship, investigate.
Choose the best next stage from goal + state; do not emit a fixed pipeline for all inputs.
If state.errors is non-empty, strongly prefer stage "fixing" unless the goal explicitly requires replanning from scratch (then "planning").
If payload.priority_guidance exists, preserve its intent in your stage/task choice.
"""


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _planner_input(goal: str, state: ProjectState) -> dict[str, Any]:
    structure = state.structure if isinstance(state.structure, dict) else {}
    mcp_caps = structure.get("mcp_capabilities") if isinstance(structure.get("mcp_capabilities"), list) else []
    payload: dict[str, Any] = {
        "goal": goal,
        "state": state.to_dict(),
        "context_digest": build_context_digest(structure),
    }
    fail_count = int(state.counters.get("command_failures", 0)) if isinstance(state.counters, dict) else 0
    if fail_count >= 3:
        handoff = state.structure.get("investigate_handoff", {}) if isinstance(state.structure, dict) else {}
        rec = handoff.get("recommended_next_actions", []) if isinstance(handoff, dict) else []
        if isinstance(rec, list) and rec:
            payload["priority_guidance"] = {
                "mode": "investigate",
                "must_consider_first": [str(x) for x in rec[:3]],
            }
        # For repeated failures, surface compact operational guidance from available capabilities.
        if mcp_caps:
            payload["debug_capability_hints"] = [
                str(x.get("tool", "")) for x in mcp_caps if isinstance(x, dict) and x.get("tool")
            ][:5]
    return payload


def _coerce_stage(raw: str) -> str:
    s = (raw or "").strip().lower()
    catalog = set(default_stage_catalog())
    if s in catalog:
        return s
    _LOG.warning("planner returned unknown stage %r; falling back to coding", raw)
    return StageId.CODING.value


def _contextual_task_hints(state: ProjectState, *, include_debug_tools: bool = False) -> list[str]:
    structure = state.structure if isinstance(state.structure, dict) else {}
    out: list[str] = []
    rag = structure.get("rag_hints")
    if isinstance(rag, list) and rag:
        out.append("先参考 rag_hints 的相关片段，再决定最小改动范围")
    skills = structure.get("skill_hints")
    if isinstance(skills, list) and skills:
        out.append(f"优先按 skill_hints 执行: {str(skills[0])}")
    caps = structure.get("mcp_capabilities")
    if include_debug_tools and isinstance(caps, list) and caps:
        tools = [str(x.get('tool', '')) for x in caps if isinstance(x, dict) and x.get("tool")]
        if tools:
            out.append(f"优先使用 mcp 工具定位问题: {', '.join(tools[:2])}")
    return out[:3]

#本地规则引擎（默认）
def plan_heuristic(goal: str, state: ProjectState, prompts_dir: Path) -> dict[str, Any]:
    _ = load_prompt(prompts_dir / "planner.txt")
    fail_count = int(state.counters.get("command_failures", 0)) if isinstance(state.counters, dict) else 0
    if state.errors:
        if fail_count >= 3:
            handoff = state.structure.get("investigate_handoff", {}) if isinstance(state.structure, dict) else {}
            rec = handoff.get("recommended_next_actions", [])
            if not isinstance(rec, list):
                rec = []
            rec = [str(x) for x in rec][:3]
            tasks = ["收集错误证据", "最小验证假设", "给出最小修复方案"]
            if rec:
                tasks = [f"按建议执行: {x}" for x in rec]
            tasks.extend(_contextual_task_hints(state, include_debug_tools=True))
            st = DynamicStage(
                stage=StageId.INVESTIGATE.value,
                tasks=tasks,
                meta={"command_failures": fail_count, "goal": goal, "recommended_next_actions": rec},
            )
            return st.to_dict()
        fix_tasks = ["根据 stderr 修复代码", "重新运行验证"]
        fix_tasks.extend(_contextual_task_hints(state, include_debug_tools=True))
        st = DynamicStage(
            stage=StageId.FIXING.value,
            tasks=fix_tasks,
            meta={"error_count": len(state.errors), "goal": goal},
        )
    elif state.current_stage == StageId.REVIEW.value and state.quality.get("review_score") is not None:
        st = DynamicStage(
            stage=StageId.QA.value,
            tasks=["执行质量自检", "评估健康分"],
            meta={"review_score": state.quality.get("review_score")},
        )
    elif state.current_stage == StageId.QA.value and state.quality.get("health_score") is not None:
        st = DynamicStage(
            stage=StageId.SHIP.value,
            tasks=["通过交付门禁", "准备 finish"],
            meta={"health_score": state.quality.get("health_score")},
        )
    elif not state.files:
        coding_tasks = ["创建初始代码文件", "运行并收集反馈"]
        coding_tasks.extend(_contextual_task_hints(state, include_debug_tools=False))
        st = DynamicStage(
            stage=StageId.CODING.value,
            tasks=coding_tasks,
            meta={"goal": goal},
        )
    elif state.progress.startswith("run_ok"):
        st = DynamicStage(
            stage=StageId.REVIEW.value,
            tasks=["确认可重复运行", "检查是否有明显质量问题"],
            meta={},
        )
    else:
        coding_tasks = ["迭代实现目标", "运行并收集反馈"]
        coding_tasks.extend(_contextual_task_hints(state, include_debug_tools=False))
        st = DynamicStage(
            stage=StageId.CODING.value,
            tasks=coding_tasks,
            meta={"goal": goal},
        )
    return st.to_dict()

#plan_with_openai() OpenAI 动态推理   
def plan_with_openai(
    goal: str,
    state: ProjectState,
    prompts_dir: Path,
    model: str,
    provider: str = "openai",
) -> dict[str, Any]:
    llm_provider = resolve_llm_provider(provider, model)
    client = create_openai_compatible_client(llm_provider)
    base = load_prompt(prompts_dir / "planner.txt")
    system = base + "\n\n" + _PLANNER_LLM_RULES
    user = json.dumps(_planner_input(goal, state), ensure_ascii=False)
    resp = client.chat.completions.create(
        model=llm_provider.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    stage = _coerce_stage(str(data.get("stage", "")))
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    tasks = [str(t) for t in tasks]
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    return DynamicStage(stage=stage, tasks=tasks, meta=meta).to_dict()


def plan(goal: str, state: ProjectState, prompts_dir: Path, config: AppConfig) -> dict[str, Any]:
    if config.planner_use_llm:
        try:
            return plan_with_openai(
                goal,
                state,
                prompts_dir,
                config.planner_model,
                provider=config.llm_provider,
            )
        except Exception as e:
            _LOG.warning("planner LLM failed (%s); using heuristic planner", e)
    return plan_heuristic(goal, state, prompts_dir)


def plan_to_json_line(goal: str, state: ProjectState, prompts_dir: Path, config: AppConfig) -> str:
    return json.dumps(plan(goal, state, prompts_dir, config), ensure_ascii=False)
