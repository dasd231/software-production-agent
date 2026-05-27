# Skill Runtime Anti-Hallucination：从提示词分层到 Skill 获取

> 位置：`agent/skill_runtime/`  
> 目标：解决任务幻化、格式幻化、思维链幻化，以及“提示词分层太松散”的问题。

## 1. 核心判断

只靠提示词说“不要幻觉”是不够的。提示词是软约束，随着项目变大，会出现：

- 多层 system/developer/task prompt 相互覆盖；
- 输出格式靠模型自觉遵守；
- Agent 擅自把任务扩大；
- 用长篇思维链制造“看起来可靠”的错觉；
- 工具、RAG、工作流、小模型职责混在一起。

本模块改成：

```text
User Goal
  -> TaskContract
  -> SkillRegistry.select()
  -> SkillBundle
      - selected SkillCard
      - FormatContract
      - ReasoningContract
  -> ContractGuard.validate()
  -> only then execute / persist / call tool
```

一句话：**先获取 Skill，再组装提示词；先校验契约，再执行动作。**

## 2. 三类幻化防线

### 2.1 任务幻化 Task Hallucination

问题：用户只让整理文档，Agent 自己加上部署、训练、删库、改密钥、联网爬取。

实现：`TaskHallucinationGuard`

- 编译 `TaskContract`：用户目标、允许范围、禁止范围、成功标准；
- 检测未授权高风险范围：deploy/delete/train/secret/network；
- 检测输出与用户目标过度漂移；
- 范围扩展只能作为建议，不能变成执行项。

### 2.2 格式幻化 Format Hallucination

问题：本该输出 JSON，结果混入 markdown；字段缺失、字段漂移、类型错。

实现：`FormatHallucinationGuard`

- `FormatContract` 声明 required/optional fields；
- `allow_extra_fields=False` 默认禁止未声明字段；
- `field_types` 校验 `str/list/dict/bool/int/number`；
- 机器执行前必须通过 schema 校验。

### 2.3 思维链幻化 Reasoning Hallucination

问题：模型输出一长段不可验证的“思维链”，甚至伪造自己确认过的事实。

实现：`ReasoningHallucinationGuard`

- 默认不允许暴露 hidden chain-of-thought；
- 禁止自由 `reasoning` 字段；
- 改为短的 `decision_brief` / `answer + evidence + risks + next_actions`；
- evidence 必须带 `evidence_id`；
- 引用未知 evidence_id 会触发违规。

## 3. Skill 获取为什么比提示词分层更关键

提示词分层的问题是：层越多越难知道哪条约束生效。Skill 获取则是把能力变成机器对象：

```python
SkillCard(
    skill_id="skill.semantic_retrieval",
    capability_tags=("semantic_retrieval", "need_slot", "rag"),
    output_contract="semantic_context_package.v1",
    guardrails=("禁止直接 user query -> topK chunks",),
)
```

运行时拿到的不是一段松散 prompt，而是：

```text
SkillBundle
  -> TaskContract
  -> selected SkillCards
  -> FormatContract
  -> ReasoningContract
```

这样 LangGraph / CommandAPI / Executor 都可以判断：

- 这次任务需要什么 Skill；
- 哪些 Skill 缺失；
- 输出 schema 是什么；
- 是否允许执行高风险动作；
- 证据是否足够支撑结论。

## 4. 当前实现文件

| 文件 | 作用 |
|---|---|
| `schemas.py` | SkillCard、TaskContract、FormatContract、ReasoningContract、SkillBundle、GuardReport |
| `registry.py` | 内置 SkillRegistry、任务类型推断、SkillBundle 装配 |
| `guards.py` | 三类幻化 guard + ContractGuard 统一入口 |
| `planner.py` | `build_skill_runtime_plan()`，输出可写入文件的 Skill Runtime 计划 |

已注册 action：

```json
{
  "type": "action",
  "action": "skill_runtime_plan",
  "args": {
    "goal": "解决任务幻化、格式幻化、思维链幻化，先获取 Skill",
    "required_skill_ids": ["skill.semantic_retrieval"],
    "explicit_scope": ["任务契约", "格式契约", "SkillBundle"],
    "output_path": "plans/skill-runtime.json"
  }
}
```

已进入：

- `agent.core.protocol.ALLOWED_ACTIONS`
- `agent.core.governance.ACTION_GOVERNANCE`
- `agent.core.executor`
- `agent.chains.registry`
- `agent.command_api`

## 5. 测试

```bash
cd software-production-agent
python -m pytest tests/test_skill_runtime_guards.py -q
```

当前覆盖：

- baseline Skill 获取；
- 合法 evidence-bound 输出通过；
- 未授权 deploy/delete/train 被拦截；
- schema 缺字段/多字段/类型错被拦截；
- hidden CoT / freeform reasoning / unknown evidence 被拦截；
- executor action 权限校验和文件输出。

## 6. 面试讲法

> 我没有继续把约束堆在提示词里，因为提示词分层在大项目里会越来越松散。我做的是 Skill-first runtime：Agent 执行前必须获取 SkillBundle，里面包含任务契约、格式契约、可见推理摘要契约和具体 SkillCard。任务幻化由 TaskContract 限制范围；格式幻化由 FormatContract 机器校验；思维链幻化则禁止输出隐藏推理，改成 evidence-bound decision brief。这样提示词只是渲染结果，真正的约束是运行时契约。

## 7. 下一步

1. 在 LangGraph-like runtime 的每个节点执行前自动 `AcquireSkillBundle`；
2. 将 SkillBundle 写入 property graph：`AgentRun -> USED_SKILL -> SkillCard`；
3. 将 GuardReport 写入质量日志，用于训练中间层小模型；
4. Diff-native 代码协同时强制获取 `skill.diff_intelligence`；
5. Research/RAG 节点默认获取 `skill.semantic_retrieval`，禁止直接 query->topK。


## 8. 当前回归结果

```text
539 passed, 1 skipped in 128.83s
```


## 9. Workflow Runtime 集成

Skill Runtime 已经不只是独立 action，而是接入了 `agent.workflow.runtime.CompiledWorkflowGraph._run()`。

开启方式：

```python
from agent.workflow.schema import WorkflowPolicy

policy = WorkflowPolicy(
    skill_runtime_enabled=True,
    skill_required_skill_ids={
        "safe_execute": ("skill.reasoning_brief",),
        "research_node": ("skill.semantic_retrieval",),
    },
    skill_explicit_scope={
        "safe_execute": ("local execution", "no production deploy"),
    },
    skill_fail_closed=True,
)
```

节点执行链路变为：

```text
workflow node selected
  -> assemble SkillBundle
  -> preflight guard
  -> execute node
  -> validate NodeResult as workflow_node_output.v1
  -> if guard ok: merge updates and route
  -> if guard failed and fail_closed: workflow FAILED
  -> append WorkflowTraceEvent with skill_bundle + skill_guard_report
```

这让 LangGraph-like runtime 具备三个新能力：

1. **节点级 Skill 获取**：每个节点可以声明需要的 Skill；
2. **节点级反幻化门禁**：输出里出现未授权部署/删除/训练、隐藏 CoT、格式漂移会失败关闭；
3. **节点级可观测**：`WorkflowTraceEvent.metadata` 记录 `skill_bundle` 与 `skill_guard_report`。

## 10. 图数据库投影

新增入口：

```python
from agent.skill_runtime import skill_runtime_to_property_graph, skill_runtime_graph_bundle
```

图谱结构：

```text
AgentRun -[:GUARDED_BY]-> SkillBundle
AgentRun -[:USED_SKILL]-> SkillCard
SkillBundle -[:GUARDED_BY]-> TaskContract
SkillBundle -[:GUARDED_BY]-> FormatContract
SkillBundle -[:GUARDED_BY]-> ReasoningContract
AgentRun -[:EVALUATED_BY]-> GuardReport
GuardReport -[:VALIDATED_OUTPUT]-> SkillBundle
Evidence(guard_violation) -[:CITED]-> GuardReport
```

这意味着 GraphRAG 可以回答：

- 这次工作流节点执行前拿了哪些 Skill？
- Guard 是否放行？
- 如果失败，是任务幻化、格式幻化还是思维链幻化？
- 哪类节点最容易触发未授权副作用？

## 11. 当前回归结果

```text
542 passed, 1 skipped
```
