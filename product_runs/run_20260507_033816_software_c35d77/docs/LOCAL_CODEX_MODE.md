# Local Codex Handoff Mode

`codex_handoff` 的目标是解决无 API quota 时的真实开发体验问题。

## What It Does

- 不调用 OpenAI/Groq API。
- 生成 `CODEX_TASK.md` 和 `codex_task.json`。
- 把需求、已有产物、验收标准、隔离边界和可选学习流水线交给当前 Codex 会话。

## What It Does Not Do

- 它不是本地隐藏大模型。
- 它不会让 Flask 后台自动调用 Codex。
- 它不会越过用户确认直接改平台源码。

## API Modes Stay Separate

- `llm` / `llm_planner` 继续使用 OPENAI/GROQ API key。
- `frontend_sandbox` 有 API key 时可调用模型，无 key 时走静态回退。
- `demo` 继续做确定性离线模板。
