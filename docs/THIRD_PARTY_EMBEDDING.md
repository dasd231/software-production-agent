# Third-Party Embedding Fabric

> 本文档是项目架构设计文档，描述第三方嵌入能力如何落地到主链/分链系统。它不是某个厂商 SDK 的复制实现，也不包含第三方私有协议。

## 目标

用户想要的不是“调用一下 Figma API”，而是类似 Figma、Coze Studio、插件市场、企业内部门户那种夸张的第三方嵌入能力：

- 外部系统能作为面板直接嵌进平台。
- 外部资源能被选择、标记、同步、进入 RAG 或方案库。
- 外部动作能通过桥接协议触发主链/分链。
- 外部事件能进入 evidence ledger，成为可审计事实。
- 后续 GitHub、Notion、Linear、Slack、企业内部 PLM/ERP/知识库可以按同一协议接入。

## 核心抽象

`agent/integrations/embedding.py` 定义 `IntegrationManifest`，每个第三方系统至少描述：

- `id` / `label` / `vendor`：稳定身份。
- `surfaces`：支持的嵌入形态。
- `capabilities`：能产生什么能力，比如设计稿引用、代码仓库引用、知识卡片、工单事件。
- `allowed_origins`：iframe 与 postMessage 白名单。
- `required_scopes` / `secret_env`：权限和密钥来源。
- `data_policy`：哪些数据可落本地，哪些必须留在第三方系统。

内置 manifest：

- `figma`：设计稿嵌入、frame selection、design token handoff、前端规格生成。
- `github`：repo/issue/PR 引用、爬虫输入、代码资产交接。
- `notion`：页面/数据库引用、知识卡片、RAG 来源同步。
- `linear`：issue/project 状态、交付证据。
- `slack`：讨论串引用、决策记录、通知回流。

## Surface 类型

| Surface | 用途 | 示例 |
| --- | --- | --- |
| `embed_panel` | 直接嵌入第三方面板 | Figma 文件 iframe |
| `resource_picker` | 选择第三方资源 | 选 GitHub repo、Notion page |
| `action_bridge` | 外部 UI 请求主链执行动作 | “把这个 frame 转成前端任务” |
| `webhook_event_source` | 第三方事件进入证据账本 | PR opened、issue updated |
| `asset_sync` | 显式同步资产快照 | 设计 token、知识卡片、代码片段 |

## Action 与 API

主链 action：

```json
{"type":"action","action":"integration_catalog","args":{"category":"design"}}
```

```json
{"type":"action","action":"integration_embed_plan","args":{"integration_id":"figma","resource_url":"https://www.figma.com/file/abc/Product","mode":"embed_panel","requested_capabilities":["frame_selection","design_token_handoff"]}}
```

生产 API：

- `GET /api/integrations`
- `POST /api/integrations/embed-plan`

本地 UI 也暴露同名 API，便于产品壳先使用同一能力。

## 安全边界

`integration_embed_plan` 不直接信任外部 URL。它会做：

- URL scheme 校验：只允许 HTTPS；本地开发可保留 localhost HTTP。
- Origin 校验：必须命中 manifest 的 `allowed_origins`。
- Surface 校验：不支持的嵌入形态直接拒绝。
- Capability 校验：请求了 manifest 不声明的能力直接拒绝。
- Sandbox 输出：iframe 必须使用受控 sandbox。
- CSP 输出：调用方必须按 plan 的 `frame-src` / `connect-src` 施加限制。

返回的 `admission.embeddable=false` 时，平台不应该打开 iframe 或接收桥接消息。

## postMessage 桥

桥接消息统一 envelope：

```json
{
  "schema": "integration_bridge_message.v1",
  "integration_id": "figma",
  "event": "selection.changed",
  "payload": {},
  "nonce": "<host-issued-nonce>",
  "correlation_id": "<trace-id>"
}
```

外部到平台的核心事件：

- `selection.changed`
- `asset.export.requested`
- `action.invoke`
- `event.emit`
- `handoff.create`

平台到外部的核心事件：

- `host.context.sync`
- `host.selection.request`
- `host.action.result`
- `host.theme.update`
- `host.token.refresh.request`

## 资产沉淀

第三方嵌入不是为了“看起来高级”，最终要进入本地资产闭环：

```text
external_selection
  -> bridge_validation
  -> evidence_ledger
  -> solution_or_training_store
```

示例映射：

- Figma `selected_frame` -> `design_asset_ref`
- Figma `design_tokens` -> `frontend_style_spec`
- GitHub `repository_snapshot` -> `github_crawl_profile_input`
- Notion `knowledge_page` -> `rag_knowledge_card`
- Linear `work_item` -> `workflow_evidence`

## 后续落地路线

1. 前端增加 Integration Drawer：读取 `/api/integrations`，展示第三方资源目录。
2. 打开 Figma Embed Panel：使用 `/api/integrations/embed-plan` 的 `surface.iframe_url` 和 sandbox。
3. 增加 Host Bridge Runtime：只接收 allowed origin + nonce 通过的消息。
4. 将 `handoff.create` 转为 workflow 节点：比如 design handoff -> research -> solution_publish。
5. 将第三方事件写入 `evidence_ledger`：形成可审计交付链。
6. 将企业内部系统也 manifest 化：PLM、ERP、需求池、知识库都通过同一 contract 接入。
