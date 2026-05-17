"""Product UI package for the software production agent.

函数流程图：
    browser
      -> agent.ui.app.create_app()
      -> Flask routes
      -> run_agent_loop()
      -> workspace artifacts / state / events

你可以继续练算法/工程化的点：
    1. UI 状态机：现在是同步请求；后续可以升级成 job queue + streaming progress。
    2. 模式路由：用户侧现在只保留 local_production/llm；后续可以接入方案检索 profile。
    3. 产物视图：现在读取工作区文件；后续可以做 artifact graph 和验收报告。
"""

from __future__ import annotations
