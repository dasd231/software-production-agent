# Adaptive Workflow Runtime：把 LangGraph 二改思想融入主项目

这不是外部学习 demo，而是 `software-production-agent` 主项目内的正式能力层：

```text
agent/workflow/
```

它的定位是：

> 在现有 AgentLoop 之上，引入 LangGraph-like 的状态图运行时；在现有 decision/reward/trace 之上，引入可观测、可中断、可优化、可版本化的 workflow policy plane。

## 为什么要做这层

原来的主链路更像固定循环：

```text
plan -> context -> decide -> execute -> reward -> maybe fix -> continue
```

这已经能跑，但还不够“二改 LangGraph”。真正的二改思想应该是：

```text
图结构稳定
条件边可学习
节点可替换
trace 可回放
policy 可优化
低置信可 interrupt
策略可版本化发布/回滚
```

## 当前落地文件

```text
agent/workflow/schema.py          WorkflowState / TraceEvent / WorkflowPolicy
agent/workflow/runtime.py         AdaptiveWorkflowGraph / checkpoint / interrupt / resume
agent/workflow/checkpoint.py      InMemory + JSONL durable checkpoint
agent/workflow/project_graph.py   面向 software-production-agent 的项目工作流图
agent/workflow/optimizer.py       trace-driven route policy optimizer
agent/workflow/policy_store.py    policy version store
agent/workflow/replay.py          logged-policy replay / 离线策略回放
agent/workflow/spec.py            graph spec / Mermaid / 面试解释导出
agent/workflow/loop_graph.py      主链路 agent_loop 语义图编译器
agent/workflow/dataset.py         小模型 route policy 训练数据导出
agent/workflow/cli.py             独立 CLI
```

测试：

```text
tests/test_adaptive_workflow_runtime.py
```

## 和已有 decision 层的关系

这层没有推翻已有算法，而是复用：

```text
agent.decision.policy.evaluate_decision_policy
agent.decision.policy.update_policy_state
agent.decision.trace.build_decision_trace
agent.decision.bandit.rank_candidates_with_ucb
```

也就是说：

```text
现有 decision = 单步动作选择智能
新增 workflow = 多步图路由与策略优化智能
```

## 当前图结构

```text
START
  -> inspect_context
  -> build_plan
  -> choose_action
  -> fast_execute / safe_execute / human_gate
  -> evaluate_outcome
  -> repair? / finalize / human_gate
  -> END
```

其中：

```text
choose_action       复用 agent.decision.policy
fast/safe_execute   表达不同执行策略分支
evaluate_outcome    更新 decision memory + trace
repair              失败后的修复分支
human_gate          低置信/高风险 interrupt
finalize            输出 workflow summary
```

## CLI

运行一次 demo：

```bash
python -m agent.workflow.cli demo --goal "优化项目并安全交付"
```

分析 trace 并生成 policy：

```bash
python -m agent.workflow.cli optimize \
  --trace-dir .agent_workflow_traces \
  --policy-store .agent_workflow_policies \
  --policy-version v1 \
  --promote
```

人工批准中断 run：

```bash
python -m agent.workflow.cli approve <run_id> \
  --trace-dir .agent_workflow_traces \
  --feedback "人工确认可以继续"
```

## 真实 agent 事件桥接

新增：

```text
agent/workflow/event_bridge.py
agent/workflow/interview.py
```

现在可以把主链路生成的：

```text
.agent_events.jsonl
```

转换成：

```text
WorkflowTraceEvent[]
```

然后直接喂给 `WorkflowOptimizer`。

命令：

```bash
python -m agent.main --demo --events --workspace ./workspace_demo
python -m agent.workflow.cli optimize-events \
  --events ./workspace_demo/.agent_events.jsonl \
  --policy-store .agent_workflow_policies \
  --policy-version from-agent-events-v1
```

这一步很关键：它证明 `agent.workflow` 不是孤立图 demo，而是能利用主项目真实运行数据做自动工作流优化。

面试报告：

```bash
python -m agent.workflow.cli interview \
  --events ./workspace_demo/.agent_events.jsonl
```

## 下一步迁移计划

现在是“旁挂式正式模块”，下一步可以逐渐把 `agent.core.agent_loop` 的内部阶段迁进来：

```text
1. 用 workflow graph 包住 plan/context/decide/execute/reward
2. 每个原有阶段变成一个 node
3. fix / investigate / ship gate 变成 conditional edge
4. .agent_events.jsonl 和 workflow_events.jsonl 合并 schema
5. WorkflowPolicy 从文件 store 升级为 GitOps/ConfigMap/数据库
6. AgentTask CRD 调用这个 workflow runtime 作为执行核心
```

这才是项目层面的 LangGraph 二改：不是“用了 LangGraph”，而是把 Agent 系统改造成可观测、可优化、可治理的图运行时。

## Canary rollout for optimized policy

新增：

```text
agent/workflow/rollout.py
```

自动优化策略不要直接全量上线。推荐流程：

```text
trace -> optimizer -> candidate policy -> canary plan -> guarded rollout -> promote/rollback
```

命令：

```bash
python -m agent.workflow.cli canary-plan \
  --events ./workspace_demo/.agent_events.jsonl \
  --candidate-policy-version from-agent-events-v1
```

## 离线回放：让“工作流优化”变成可验收

新增：

```text
agent/workflow/replay.py
```

命令：

```bash
python -m agent.workflow.cli replay \
  --events ./workspace_demo/.agent_events.jsonl \
  --format markdown
```

它做的是保守 logged-policy replay：

```text
只统计“历史实际走过的 route_choice”刚好等于“候选策略当前 top choice”的事件。
```

这不是因果反事实证明，也不会假装知道没走过的分支会怎样。它的价值是：

```text
1. 检查候选策略在历史日志上的覆盖率。
2. 暴露低覆盖/高风险 route。
3. 给 canary 上线前增加一道离线验收。
```

这点面试很重要：成熟系统不会说“optimizer 觉得好就上线”，而是：

```text
trace -> optimize -> replay -> canary -> promote / rollback
```

## 图结构自解释

新增：

```text
agent/workflow/spec.py
```

导出 Mermaid：

```bash
python -m agent.workflow.cli explain --format mermaid
```

导出面试解释稿：

```bash
python -m agent.workflow.cli explain --format markdown
```

这个能力用于三件事：

```text
1. 让 workflow graph 可视化，方便协同开发。
2. 让 conditional edge 和 route_key 可解释。
3. 让“LangGraph 二改”不是嘴上讲，而是能导出结构、策略和优化 hook。
```

## 主链路迁移桥：agent_loop semantic graph

新增：

```text
agent/workflow/loop_graph.py
```

它解决一个更实际的问题：

```text
当前 agent.core.agent_loop 是稳定主链路，不能为了炫技强行推倒。
所以先把它编译成“语义阶段图”，再从 .agent_events.jsonl 反推真实路径和瓶颈。
```

导出主链路语义图：

```bash
python -m agent.workflow.cli loop-spec --format mermaid
python -m agent.workflow.cli loop-spec --format markdown
```

分析真实事件：

```bash
python -m agent.workflow.cli loop-analyze \
  --events ./workspace_demo/.agent_events.jsonl \
  --format markdown
```

这一步是从“旁挂 workflow”走向“替换/吸收 agent_loop”的迁移桥：

```text
stable agent_loop
  -> semantic graph spec
  -> event path analysis
  -> identify conditional edges
  -> migrate stages into Workflow nodes
```

现在已经明确的优化面：

```text
plan -> context              context_budget_policy
context -> decision_policy   evidence_quality_gate
decision_policy -> decide    candidate_action_policy
quality_gate -> fix          repair_policy
```

这几个点后续可以接小模型做路由，或者接 optimizer 生成 route_weights。

## 小模型训练数据导出：从规则到 route policy model

新增：

```text
agent/workflow/dataset.py
```

命令：

```bash
python -m agent.workflow.cli export-route-dataset \
  --events ./workspace_demo/.agent_events.jsonl \
  --output ./datasets/route_policy.jsonl \
  --format markdown
```

导出的每行是一个 route-policy 训练样本：

```json
{
  "route_key": "execution_action",
  "route_choice": "production_check",
  "reward": 0.87,
  "quality_label": "positive",
  "features": {
    "node": "execute_action",
    "status": "ok",
    "score_bucket": "0.75-1.00",
    "confidence_bucket": "0.75-1.00",
    "latency_bucket": "lt_1s"
  },
  "target": {
    "task": "workflow_route_policy",
    "label": "production_check",
    "sample_weight": 0.87
  }
}
```

这给后续“小模型接管中间层路由”留下了训练接口：

```text
真实 agent events
  -> WorkflowTraceEvent
  -> route_policy.jsonl
  -> 小模型 / bandit / lightweight classifier
  -> WorkflowPolicy route_weights
```

面试表达可以很直接：

```text
我没有让大模型判断所有流程分支；高频、低语义、可统计的路由决策会沉淀为 route-policy dataset，后续交给小模型或 bandit，LLM 只负责高价值推理。
```


## Skill Runtime Guard：节点级反幻化门禁

`WorkflowPolicy` 现在可以打开 `skill_runtime_enabled=True`。打开后，每个 workflow node 执行前都会获取 `SkillBundle`，执行后会用 `ContractGuard` 校验 `NodeResult`。

关键字段：

```python
WorkflowPolicy(
    skill_runtime_enabled=True,
    skill_required_skill_ids={"node_name": ("skill.reasoning_brief",)},
    skill_explicit_scope={"node_name": ("local planning only",)},
    skill_fail_closed=True,
)
```

这把 LangGraph-like 工作流从“节点能跑”推进到“节点有能力契约、有输出契约、有反幻化门禁、有图谱证据”。
