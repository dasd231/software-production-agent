"""Agent Brain — 主控动作决策面（与执行循环解耦）。

函数流程图：
    AgentBrain.decide()
      -> 子类输出单行 Action JSON
      -> protocol.parse_and_validate_action_line()
      -> executor.run_action()

    ScriptedDemoBrain.decide()
      -> write_bad
      -> run_broken
      -> fix_or_abort
      -> run_fixed
      -> finish

    OpenAIBrain.decide()
      -> resolve_llm_provider(provider, model)
      -> create_openai_compatible_client()
      -> build system/action prompt
      -> build_context_digest(state.structure)
      -> chat.completions.create(response_format=json_object)
      -> parse/validate action
      -> invalid 时追加纠错提示重试一次

你可以继续练算法/工程化的点：
    1. 多模型路由：现在 provider/model 由 UI/配置选择；可按任务阶段动态选择模型。
    2. 格式可靠性：现在依赖 JSON object mode；可增加 schema mode / repair model / strict parser。
    3. Prompt 预算：可以按 stage 分配 transcript、RAG、events 的 token 配额。
    4. 降级策略：provider 429/5xx 时可以切换备用 provider 或离线模板。
    5. 行为学习：把 action valid rate、reward_avg、latency 回写到模型选择策略。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent.context.digest import build_context_digest
from agent.core.protocol import ProtocolError, parse_and_validate_action_line
from agent.llm.providers import create_openai_compatible_client, resolve_llm_provider
from agent.memory.project_state import ProjectState
from agent.memory.session import SessionMemory
from agent.pipeline.stages import StageId


class AgentBrain(ABC):
    """主控：输出一行可通过协议校验的 Action JSON。"""

    last_usage: dict[str, int] = {}

    @abstractmethod
    def decide(
        self,
        goal: str,
        plan: dict[str, Any],
        state: ProjectState,
        last_result: dict[str, Any] | None,
        session: SessionMemory | None = None,
    ) -> str:
        pass

    def fix(
        self,
        error_text: str,
        goal: str,
        plan: dict[str, Any],
        state: ProjectState,
        session: SessionMemory | None = None,
    ) -> str:
        return self.decide(
            goal,
            plan,
            state,
            {"synthetic_error": error_text, "_note": "fix_round"},
            session=session,
        )


class ScriptedDemoBrain(AgentBrain):
    """离线闭环演示（不调用 LLM）。"""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._phase = "write_bad"
        self.last_usage = {}

    def decide(
        self,
        goal: str,
        plan: dict[str, Any],
        state: ProjectState,
        last_result: dict[str, Any] | None,
        session: SessionMemory | None = None,
    ) -> str:
        _ = goal, plan, state, session
        import sys

        py = sys.executable

        if self._phase == "write_bad":
            self._phase = "run_broken"
            bad = (
                "# intentional typo for demo fix loop\n"
                "from flusk import Flask\n"
                "app = Flask(__name__)\n"
                "@app.get('/hello')\n"
                "def hello():\n"
                "    return 'ok'\n"
                "if __name__ == '__main__':\n"
                "    import sys\n"
                "    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':\n"
                "        c = app.test_client()\n"
                "        r = c.get('/hello')\n"
                "        print(r.status_code, r.get_data(as_text=True))\n"
                "        sys.exit(0 if r.status_code == 200 else 1)\n"
                "    app.run(host='127.0.0.1', port=5055, debug=False)\n"
            )
            return json.dumps(
                {"type": "action", "action": "write_file", "args": {"path": "app.py", "content": bad}},
                ensure_ascii=False,
            )

        if self._phase == "run_broken":
            self._phase = "fix_or_abort"
            return json.dumps(
                {
                    "type": "action",
                    "action": "run_command",
                    "args": {"command": f'"{py}" app.py selftest', "timeout": 30.0},
                },
                ensure_ascii=False,
            )

        if self._phase == "fix_or_abort":
            if last_result and last_result.get("ok"):
                self._phase = "done"
                return json.dumps(
                    {"type": "action", "action": "finish", "args": {"reason": "broken import unexpectedly ran"}},
                    ensure_ascii=False,
                )
            self._phase = "run_fixed"
            good = (
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
                "@app.get('/hello')\n"
                "def hello():\n"
                "    return 'ok'\n"
                "if __name__ == '__main__':\n"
                "    import sys\n"
                "    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':\n"
                "        c = app.test_client()\n"
                "        r = c.get('/hello')\n"
                "        print(r.status_code, r.get_data(as_text=True))\n"
                "        sys.exit(0 if r.status_code == 200 else 1)\n"
                "    app.run(host='127.0.0.1', port=5055, debug=False)\n"
            )
            return json.dumps(
                {"type": "action", "action": "write_file", "args": {"path": "app.py", "content": good}},
                ensure_ascii=False,
            )

        if self._phase == "run_fixed":
            self._phase = "done"
            return json.dumps(
                {
                    "type": "action",
                    "action": "run_command",
                    "args": {"command": f'"{py}" app.py selftest', "timeout": 30.0},
                },
                ensure_ascii=False,
            )

        return json.dumps({"type": "action", "action": "finish", "args": {"reason": "demo complete"}}, ensure_ascii=False)


def _brain_parse_line(line: str) -> dict[str, Any]:
    return parse_and_validate_action_line(line.strip())


def _build_user_payload(
    goal: str,
    plan: dict[str, Any],
    state: ProjectState,
    last_result: dict[str, Any] | None,
    transcript: str,
) -> dict[str, Any]:
    structure = state.structure if isinstance(state.structure, dict) else {}
    payload: dict[str, Any] = {
        "goal": goal,
        "plan": plan,
        "state": state.to_dict(),
        "last_result": last_result,
        "recent_transcript": transcript,
        "context_digest": build_context_digest(structure),
    }
    if str(plan.get("stage", "")) == StageId.INVESTIGATE.value:
        meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
        rec = meta.get("recommended_next_actions", []) if isinstance(meta, dict) else []
        if isinstance(rec, list) and rec:
            payload["priority_guidance"] = {
                "mode": "investigate",
                "must_consider_first": [str(x) for x in rec[:3]],
                "policy": "Prefer these guidance actions before proposing new exploratory actions.",
            }
    return payload


class OpenAIBrain(AgentBrain):
    """OpenAI-compatible Chat Completions：强制 JSON 对象，降低格式失控。"""

    def __init__(
        self,
        prompts_dir: Path,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        *,
        client_timeout: float | None = None,
        client_max_retries: int | None = None,
    ) -> None:
        self.prompts_dir = prompts_dir
        self.provider = resolve_llm_provider(provider, model)
        self.model = self.provider.model
        self.client_timeout = client_timeout
        self.client_max_retries = client_max_retries
        self.last_usage = {}

    def decide(
        self,
        goal: str,
        plan: dict[str, Any],
        state: ProjectState,
        last_result: dict[str, Any] | None,
        session: SessionMemory | None = None,
    ) -> str:
        client = create_openai_compatible_client(
            self.provider,
            timeout=self.client_timeout,
            max_retries=self.client_max_retries,
        )
        system = (self.prompts_dir / "system.txt").read_text(encoding="utf-8")
        action_txt = (self.prompts_dir / "action.txt").read_text(encoding="utf-8")
        transcript = session.transcript_for_prompt(36) if session else ""
        user = json.dumps(_build_user_payload(goal, plan, state, last_result, transcript), ensure_ascii=False)
        last_err: str | None = None
        user_msg = user
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system + "\n\n" + action_txt},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.1 if attempt == 0 else 0.0,
                    response_format={"type": "json_object"},
                )
                raw = (resp.choices[0].message.content or "").strip()
                usage = getattr(resp, "usage", None)
                self.last_usage = {
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                }
                data = json.loads(raw)
                if data.get("type") != "action" and "action" in data:
                    data = {"type": "action", "action": data.get("action"), "args": data.get("args") or {}}
                line = json.dumps(data, ensure_ascii=False)
                _brain_parse_line(line)
                return line
            except (json.JSONDecodeError, ProtocolError, KeyError, ValueError) as e:
                last_err = str(e)
                user_msg = user + (
                    f"\n\nYour previous output was invalid: {last_err}. "
                    "Emit exactly one JSON object with keys type, action, args per action.txt."
                )
        raise RuntimeError(f"OpenAIBrain could not produce valid action: {last_err}")
