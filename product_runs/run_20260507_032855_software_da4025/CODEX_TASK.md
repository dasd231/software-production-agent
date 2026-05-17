# Codex Handoff Task

这个 run 不是弱离线模板，也不调用 OpenAI/Groq API。它是一个本地接管任务包：
用户在产品 UI 提交需求，本地 shell 生成任务包，然后由当前 Codex 会话读取并执行。

## Goal

```text
写一个人员管理系统
```

## Workspace

`E:\Agent\Demo1\software-production-agent\product_runs\run_20260507_032855_software_da4025`

## Pipeline Layers

- `requirement.normalize` - 需求澄清与验收标准: 抽取项目类型、核心实体、页面、API、数据模型、验收条件。
- `architecture.plan` - 架构方案: 确定前端、后端、存储、测试、沙盒预览和交付结构。
- `implementation.generate` - 软件生产: 在当前 run workspace 内生成或改进用户产物。
- `sandbox.verify` - 沙箱运行测试: 只在产物目录内运行可控 smoke check，不触碰平台源码。
- `delivery.package` - 交付封装: 更新 README、交付清单、预览入口和 ZIP 可下载产物。

## Acceptance Criteria

- 所有用户可见产物必须写在本次 product_runs/<run_id> 工作区内。
- 不得修改 software-production-agent 平台源码，除非用户在 Codex 会话里明确要求。
- 需要生成 README、运行说明、验收清单和可下载产物。
- 如果是管理系统，必须包含业务场景、数据模型、CRUD、API 契约、测试说明和可预览界面。
- 运行测试或构建前先说明命令目的；失败时保留错误摘要和下一步修复建议。

## Existing Artifacts

- 暂无上一版用户产物

## Execution Rules For Codex

- 默认只修改本 run workspace 内的用户产物。
- 不要改 `software-production-agent/` 平台源码，除非用户明确把任务改成“继续开发平台”。
- 如果需要 Web Search、GitHub 搜索、Repo 下载、RAG 或沙箱测试，先把证据/结果写入 `learning/` 或 `docs/`。
- 完成后写 `RESULT_SUMMARY.md`，列出变更文件、验证结果、未完成风险和下一轮建议。
- 如果任务太大，先交付一个成熟、可预览、可下载、可继续迭代的垂直切片。

## Suggested First Commands

```powershell
Get-ChildItem -Recurse -File "E:\Agent\Demo1\software-production-agent\product_runs\run_20260507_032855_software_da4025" | Select-Object FullName
Get-Content "E:\Agent\Demo1\software-production-agent\product_runs\run_20260507_032855_software_da4025\codex_task.json"
```
