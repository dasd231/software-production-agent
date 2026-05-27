# LangGraph 二改 / 自动工作流优化面试讲稿

这份文档服务于面试表达：你要讲的不是“我会用 LangGraph”，而是：

> 我把软件生产 Agent 改造成了一个可观测、可中断、可优化、可版本化的图运行时系统。

## 1. 一句话项目定位

```text
software-production-agent 是面向软件生产任务的 Agent 系统。
我在主项目里新增了 agent.workflow 层，把固定 agent loop 演进为 LangGraph-like adaptive workflow runtime。
```

关键词：

```text
StateGraph
Conditional edge
Checkpoint / resume
Human interrupt
Reward trace
Bandit policy
Policy versioning
Offline optimization
Logged-policy replay
Canary / rollback
Graph explainability
Agent-loop semantic graph
Route-policy dataset
```

## 2. 为什么不是简单 LangGraph demo

普通 LangGraph demo：

```text
写几个 node
连几条 edge
跑一个问答流程
```

这个项目里的二改思想：

```text
1. 复用主项目已有 agent.decision 的 policy/reward/trace/bandit。
2. 新增 agent.workflow，负责多步图路由策略。
3. 真实 .agent_events.jsonl 可以转换成 workflow traces。
4. optimizer 根据真实运行 trace 生成下一版 WorkflowPolicy。
5. PolicyStore 支持版本化、promote、未来 rollback/canary。
6. replay/spec 让候选策略能离线验收，让图结构能 Mermaid/Markdown 导出。
7. loop_graph 把现有稳定 agent_loop 编译成语义图，作为逐步迁移到自适应 workflow 的桥。
8. dataset 把真实 route trace 导出成小模型训练 JSONL，让路由策略未来可学习。
```

所以它不是孤立 demo，而是和主项目已有事件系统、决策系统、奖励系统接起来的。

## 3. 架构分层

```text
agent.core.agent_loop
  现有稳定主链路：plan/context/decide/execute/reward

agent.decision
  单步动作选择：heuristic + bandit + reward update

agent.workflow
  多步工作流优化：graph runtime + conditional routing + optimizer

agent.analytics
  事件分析：inspect-events/history gate
```

新的核心分工：

```text
agent.decision 解决“下一步选什么动作”
agent.workflow 解决“整个任务走哪条路径”
```

## 4. 当前 workflow 图

```text
START
  -> inspect_context
  -> build_plan
  -> choose_action
  -> fast_execute / safe_execute / human_gate
  -> evaluate_outcome
  -> repair / finalize / human_gate
  -> END
```

其中：

```text
choose_action       复用 evaluate_decision_policy
evaluate_outcome    复用 update_policy_state + build_decision_trace
human_gate          对应 LangGraph interrupt 思想
checkpoint          支持 durable resume
optimizer           根据 route trace 调 route_weights
```

## 5. 面试重点：二改改在哪里

### 改造点 A：Optimization Plane

LangGraph 本身偏运行时，我增加的是优化面：

```text
TraceEvent -> Reward -> RouteStats -> WorkflowOptimizer -> WorkflowPolicy
```

这让工作流不是静态 DAG，而是可以根据历史表现调整条件边权重。

### 改造点 B：事件桥接

新增：

```text
agent/workflow/event_bridge.py
```

作用：

```text
.agent_events.jsonl -> WorkflowTraceEvent[] -> WorkflowOptimizer
```

这说明已有 agent_loop 的真实运行数据可以反哺新 workflow。

### 改造点 C：Policy Versioning

新增：

```text
agent/workflow/policy_store.py
```

作用：

```text
保存策略版本
promote 当前版本
未来支持 canary / rollback / GitOps 发布
```

### 改造点 D：Human Interrupt

低置信/高风险路线进入：

```text
human_gate
```

可以 patch state 后 resume。

### 改造点 E：Logged-policy Replay

新增：

```text
agent/workflow/replay.py
```

它不是夸大成“离线证明新策略一定更好”，而是保守地做：

```text
历史 route_choice == 候选策略 top choice 的样本才纳入 replay 评分
```

因此它能回答面试官会追问的成熟度问题：

```text
你怎么避免 optimizer 过拟合？
你怎么知道候选策略没有在低覆盖 route 上冒险？
你怎么决定能不能 canary？
```

答法：

```text
我先看 replay coverage、accepted reward、route-level risk，再进入 canary。
低覆盖不 promotion，只做 shadow/exploration 或小流量灰度。
```

### 改造点 F：Graph Spec / Mermaid 导出

新增：

```text
agent/workflow/spec.py
```

它能把 project workflow 导出为：

```text
json
markdown
mermaid
```

意义：

```text
这让“二改 LangGraph”具备工程可解释性：图结构、条件边、优化 hook 都能被审查和协作，而不是藏在代码里。
```

### 改造点 G：Agent Loop Semantic Graph

新增：

```text
agent/workflow/loop_graph.py
```

这是回答“你怎么把老系统迁移成图运行时”的关键。

我没有直接重写稳定的 `agent.core.agent_loop`，而是先做了迁移桥：

```text
agent_loop 源码语义
  -> semantic graph spec
  -> .agent_events.jsonl path analysis
  -> 找出真实条件边和瓶颈
  -> 逐步迁移成 Workflow node
```

可以导出：

```bash
python -m agent.workflow.cli loop-spec --format mermaid
python -m agent.workflow.cli loop-analyze \
  --events ./workspace_demo/.agent_events.jsonl \
  --format markdown
```

这比“我直接套 LangGraph”成熟，因为它符合工程迁移原则：

```text
先观测，再建模；先旁路验证，再替换主链路。
```

### 改造点 H：Route-policy Dataset

新增：

```text
agent/workflow/dataset.py
```

它把 `.agent_events.jsonl` 转成小模型可吃的 JSONL：

```bash
python -m agent.workflow.cli export-route-dataset \
  --events ./workspace_demo/.agent_events.jsonl \
  --output ./datasets/route_policy.jsonl \
  --format markdown
```

每条样本包含：

```text
route_key
route_choice
reward
quality_label
features
target / sample_weight
```

这回答一个更前沿的问题：

```text
多 Agent 系统里，哪些决策该让 LLM 做，哪些该交给小模型？
```

我的划分是：

```text
LLM：复杂语义理解、计划、代码推理。
小模型 / bandit：高频、低语义、可统计的路由分支，例如执行策略、修复策略、context budget。
```

## 6. 可以现场演示的命令

跑 workflow demo：

```bash
python -m agent.workflow.cli demo --goal "优化项目并安全交付"
```

优化 workflow trace：

```bash
python -m agent.workflow.cli optimize \
  --trace-dir .agent_workflow_traces \
  --policy-store .agent_workflow_policies \
  --policy-version v1 \
  --promote
```

用真实 agent 事件做优化：

```bash
python -m agent.main --demo --events --workspace ./workspace_demo
python -m agent.workflow.cli optimize-events \
  --events ./workspace_demo/.agent_events.jsonl \
  --policy-store .agent_workflow_policies \
  --policy-version from-agent-events-v1
```

生成面试 readiness 报告：

```bash
python -m agent.workflow.cli interview \
  --events ./workspace_demo/.agent_events.jsonl
```

离线回放候选策略：

```bash
python -m agent.workflow.cli replay \
  --events ./workspace_demo/.agent_events.jsonl \
  --format markdown
```

导出图结构：

```bash
python -m agent.workflow.cli explain --format mermaid
python -m agent.workflow.cli explain --format markdown
```

导出现有 agent_loop 的迁移图：

```bash
python -m agent.workflow.cli loop-spec --format mermaid
python -m agent.workflow.cli loop-analyze \
  --events ./workspace_demo/.agent_events.jsonl \
  --format markdown
```

导出 route-policy 训练集：

```bash
python -m agent.workflow.cli export-route-dataset \
  --events ./workspace_demo/.agent_events.jsonl \
  --output ./datasets/route_policy.jsonl \
  --format markdown
```

## 7. 诚实说当前边界

应该诚实表达：

```text
当前还不是完整替代 agent_loop 的生产 workflow engine。
现在是旁挂式正式模块，先接入真实 trace 和 policy optimizer。
下一步会逐步把 agent_loop 的 plan/context/decide/execute/reward 迁移为 node。
replay 是 logged-policy screening，不是因果证明；上线仍然必须经过 canary guardrails。
```

这反而更成熟：没有为了炫技破坏稳定主链路。

## 8. 你可以怎么回答“为什么不用原生 LangGraph？”

答法：

```text
我不是排斥 LangGraph，而是先把核心机制抽象出来，避免早期被框架绑定。
目前项目内实现了 StateGraph、checkpoint、interrupt、conditional routing、trace optimizer。
后续如果接原生 LangGraph，可以把 agent.workflow 的 node/policy/optimizer 迁成 LangGraph StateGraph 的执行后优化层。
```

一句话：

```text
LangGraph 负责图执行；我的二改重点是工作流自优化与项目事件闭环。
```

## 9. 下一步高级路线

```text
1. 把 agent_loop 的每个阶段迁成 node。
2. 把 fix/investigate/ship_gate 改成 conditional edge。
3. 把 low confidence 自动 interrupt。
4. 把 policy version 接 GitOps/ConfigMap。
5. 用小模型学习 route policy。
6. 把低分 trace 导出成蒸馏数据。
7. 接 K8s AgentTask CRD，让每个 AgentTask 对应一个 workflow run。
```

## 10. 自优化策略如何安全上线

这是面试里很容易拉开差距的点：

```text
自动优化不能直接全量上线。
```

新增：

```text
agent/workflow/rollout.py
```

它会根据 optimizer report 生成 canary plan：

```bash
python -m agent.workflow.cli canary-plan \
  --events ./workspace_demo/.agent_events.jsonl \
  --candidate-policy-version from-agent-events-v1
```

输出包括：

```text
initial_traffic_percent
promotion_steps
guardrails
rollback / pause 条件
```

推荐面试表达：

```text
我把自优化拆成 propose 和 rollout 两步。optimizer 只生成候选策略，rollout plan 决定灰度比例和回滚闸门。这样可以避免小样本过拟合或者错误 reward 造成策略漂移。
```

关键 guardrails：

```text
success_rate_delta
avg_reward_delta
p95_latency_delta
human_interrupt_rate_delta
```
