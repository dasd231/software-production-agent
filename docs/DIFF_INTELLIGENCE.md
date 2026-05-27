# Diff Intelligence：Vibe Coding / CLI / 多 Agent Patch 协同

> 位置：`agent/diff_intelligence/`  
> 目的：把代码变更从“Agent 随便改文件”升级为 PatchProposal / Hunk / Risk / Test / Rollback 的可审计协同对象。

## 为什么要做

Vibe Coding 的核心工件不是聊天文本，而是 diff。多 Agent 协同时，如果每个 Agent 都直接改文件，会出现：

- 修改冲突；
- 不知道哪个 hunk 引入风险；
- 测试影响不可见；
- 回滚困难；
- 审查时只能读最终文件，看不到意图。

所以本项目把 diff 变成一等对象。

## 当前实现

代码：`agent/diff_intelligence/patch.py`

核心对象：

- `DiffHunk`
- `PatchProposal`
- `parse_unified_diff()`
- `build_patch_proposal()`
- `patch_proposal_to_mermaid()`

输出：

```text
patch_proposal.v1
```

包含：

- files_changed；
- hunks；
- added/removed/context lines；
- symbols；
- risk_level；
- risk_reasons；
- test_suggestions；
- rollback_strategy。

## 和 Skill Runtime 的关系

代码协同节点默认应该获取：

```text
skill.diff_intelligence
```

这意味着代码 Agent 不能直接写文件，而应该先生成 PatchProposal，经过风险/测试/回滚检查后再应用。

## 下一步

1. `PatchProposal -> PropertyGraph`；
2. `PatchConflictScanner`；
3. `TestImpactAnalyzer`；
4. `CommandAPI` 中把代码执行 action 包装成 patch-first；
5. 与 CI 结果、review 结果、rollback 结果闭环。
