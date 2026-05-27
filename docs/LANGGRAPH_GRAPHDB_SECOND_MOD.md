# LangGraph 二改 + 图数据库 Agent Memory

这份文档把项目里的 LangGraph 思想和图数据库思想显性化。之前的 `agent.workflow` 已经有图运行时、checkpoint、interrupt、replay、optimizer，但表达上更像“自研 workflow”。这里补的是更明确的二改定位：

```text
LangGraph-like runtime
  + graph database lineage/checkpoint
  + graph-RAG Agent memory
  + route policy replay/canary/rollback
  + human interrupt as graph patch
```

入口：

```text
agent/graph_runtime/
tests/test_graph_runtime_plan.py
```

executor action：

```json
{
  "type": "action",
  "action": "graph_runtime_plan",
  "args": {
    "goal": "LangGraph 二改 + 图数据库 Agent memory",
    "output_path": "plans/graph-runtime.json"
  }
}
```

权限：

```text
graph:plan + workspace:write
```

事件日志进入图数据库：

```json
{
  "type": "action",
  "action": "graph_events_ingest",
  "args": {
    "events_path": ".agent_events.jsonl",
    "query": "run_command failed human review",
    "output_path": "plans/event-graph.json"
  }
}
```

权限：

```text
graph:write + workspace:read + workspace:write
```

## 1. 二改不是“会用 LangGraph”

普通 LangGraph demo 通常是：

```text
定义 State
写几个 node
加 conditional edge
invoke
```

项目里的二改应该讲成：

```text
我把 Agent loop 改造成可观测、可中断、可回放、可学习、可治理的图运行时。
```

显式二改点：

1. **GraphState schema hardening**  
   State 不只是 messages，还包含 evidence_subgraph、policy_version、risk、reward、graph_checkpoint。

2. **Graph database checkpointer**  
   checkpoint 不只是 JSON 快照；每次 node/edge/action/evidence/reward 都写 property graph lineage。

3. **Conditional edge optimizer**  
   条件边不是写死 if，而是 route policy。策略由历史 Reward/Decision/Action 子图优化。

4. **Human interrupt as graph patch**  
   人工介入不是日志字符串，而是 `HumanReview` 节点和 `PATCHED_STATE` 关系。

5. **Subgraph contracts**  
   research、coding、sandbox、training、PV slicing 都可以作为子图，有输入输出契约。

6. **Replay / canary / rollback**  
   `PolicyVersion` 节点连接历史运行。只有 replay coverage 和 graph risk 过线才灰度。

7. **Graph-RAG for Agent memory**  
   规划前不是只检索文本，而是查找相似成功/失败子图。

## 2. 图数据库 schema

核心节点：

```text
AgentRun
WorkflowNode
Decision
Action
Evidence
Artifact
Reward
PolicyVersion
HumanReview
```

核心关系：

```text
STARTED_AT
NEXT
MADE
ROUTED_TO
EXECUTED
CITED
PRODUCED
REWARDED_BY
USED_POLICY
REQUIRES_REVIEW
PATCHED_STATE
SIMILAR_FAILURE
```

这样能回答：

- 为什么这次走 safe_execute？
- 最终产物引用了哪些证据？
- 哪类失败反复出现？
- 哪个 policy version 导致低分路线？
- 人工介入是否真的降低了风险？

## 3. 和已有模块的关系

```text
agent.workflow
  本地 LangGraph-like runtime：node / edge / router / checkpoint / optimizer

agent.graph_runtime
  显性二改控制面：graph DB schema / graph memory / Cypher seed / 面试表达

agent.core.agent_loop
  稳定主链路，后续逐步迁移到 graph runtime

agent.evaluation.automation_scorecard
  评价图运行时是否真的提升有效自动化率
```

## 4. 面试表达模板

可以这样说：

> 我没有直接堆 LangGraph demo，而是做了一个 LangGraph-like 二改层。  
> 第一层是图编排，支持 conditional edge、interrupt、checkpoint、replay 和 route policy。  
> 第二层是图数据库，把 AgentRun、Decision、Action、Evidence、Artifact、Reward、PolicyVersion 持久化成 property graph。  
> 这样每次 Agent 决策都能追溯：它为什么这么选、证据来自哪里、产物是什么、奖励如何、策略版本是否需要回滚。  
> 图数据库不只是存日志，它还能做 Graph-RAG：从历史成功/失败子图里找相似模式，反哺下一轮规划。

## 5. 当前边界

当前已经完成：

- property graph 抽象
- demo graph
- graph runtime plan
- Cypher seed 导出
- `.agent_events.jsonl` -> property graph ingest
- Graph-RAG 子图检索
- Neo4j/Memgraph Cypher import bundle adapter
- PolicyVersion replay/canary review：低覆盖、高失败率、高人工介入率会 hold
- executor action
- pytest 覆盖

下一步才是真实图数据库执行面：

- Neo4j/Memgraph online Bolt writer
- route policy replay/canary 与真实线上灰度联动
