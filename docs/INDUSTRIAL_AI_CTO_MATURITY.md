# Industrial AI CTO Maturity Roadmap

这份文档回答一个更严肃的问题：项目如何从“强原型”走到安全关键/军工工业级 CTO 审查能站得住的成熟度。

边界声明：这里讨论的是工业 AI 平台的软件工程成熟度、治理、安全、可靠性、审计和合规证据，不涉及武器化用途或作战能力。

## 一句话结论

你的项目已经有了正确的骨架：协议化 action、执行器守门、RAG、方案库、训练分链、GitHub 爬取画像、资源中心、Model Plane、证据账本、企业技术栈规划。

但离 CTO 拷打级成熟度还差四类硬东西：

1. **执行编排从“能调用 action”升级为“workflow executor + resource lease + queue”**。
2. **模型/RAG/Workflow 都版本化，并且支持灰度、回滚和回放**。
3. **所有训练样本、外部证据、生成产物都有 evidence ledger 和治理报告**。
4. **CI/CD、供应链、观测、事故演练和合规证据自动化**。

## 成熟度等级

| Level | 名称 | 判断标准 |
| --- | --- | --- |
| L0 | Prototype | 能跑 demo，但不可审计、不可回滚 |
| L1 | Repeatable | 固定流程可重复，基本测试可通过 |
| L2 | Controlled | action、权限、资源和路径有守门 |
| L3 | Auditable | manifest、ledger、eval、governance 可回放 |
| L4 | Resilient | 灰度、回滚、SLO、弹性、事故响应可演练 |
| L5 | Mission-grade | 多租户、供应链、模型治理、合规证据和灾备闭环 |

当前项目粗略处在 **L2-L3 之间**：很多关键模块已经有了，但生产执行器、模型/RAG 灰度、供应链门禁和运行时治理还没完全闭环。

## CTO 会拷问什么

### 模型治理

- 每个回答能否回放到 `model_version`、`workflow_version`、`rag_index_version`？
- 新模型上线前 action JSON 合法率、RAG 忠实度、延迟和安全评测阈值是多少？
- 模型拥塞、异常或幻觉升高时怎么一键回滚？

必须准备：

- model registry
- eval report
- gateway routing log
- rollback drill record

### 多 Agent 控制

- 多个 Agent 同时写 workspace 时怎么防止互相覆盖？
- GPU、爬虫、训练、外部 API 怎么做资源租约和公平队列？
- 外部 API 不可用时哪些任务降级，哪些任务阻断？

必须准备：

- workflow manifest
- resource lease table
- tool gateway policy
- event trace

### RAG 和数据治理

- RAG 证据是否有来源、版本、权限和脱敏记录？
- 训练样本如何证明不是从低质量聊天或受限代码里污染出来的？
- active/candidate RAG index 如何灰度和回滚？

必须准备：

- evidence ledger
- data classification
- training governance report
- index diff report

### 发布与事故响应

- workflow 或模型更新从提交到上线经过哪些强制门禁？
- 是否支持 canary、blue-green、feature flag 和 kill switch？
- 事故发生后 30 分钟内能否定位到租户、模型、工具调用和证据来源？

必须准备：

- CI pipeline
- Argo rollout history
- SLO dashboard
- incident runbook

## 非协商门禁

这些不是“最好有”，而是进入军工工业级审查前必须有：

1. 所有真实执行必须经过 `protocol.py` / `executor.py`。
2. 模型、workflow、RAG 任何一个上线都必须有 eval 和 rollback plan。
3. 训练样本必须有 evidence lineage 和 governance report。
4. 外部 API 必须有 timeout、fallback、audit 和 contract test。
5. 企业发布必须有 SBOM、secret scan、license/CVE gate 和签名产物。
6. 所有 run 必须能根据 `run_id` 回放输入、证据、模型、工具调用和产物。

## 0-30 天：从强原型到可控工程

目标：让系统能被 CTO 看出“边界清楚、执行可控”。

交付：

- mission profile 模板：允许场景、禁止场景、SLO、数据等级、审批人。
- workflow executor MVP：从 `workflow.v1` 逐节点执行 action。
- resource lease MVP：GPU slot、crawler slot、training slot、external API slot。
- CI 加入 protocol、executor、enterprise_stack、industrial_maturity、security smoke tests。
- `model_runtime_status` 接入资源中心和告警。

## 30-90 天：从可控工程到可审计平台

目标：每次生成、检索、训练和发布都有证据。

交付：

- model registry：base model、adapter、quantization、prompt template、eval score、rollout stage。
- evidence ledger 作为训练样本唯一入口。
- RAG active/candidate index 双版本。
- run manifest、solution manifest、training governance report 全部进入 resource registry。
- OpenTelemetry trace id 贯穿 Agent、Tool、RAG、Model Gateway。

## 90-180 天：从可审计平台到弹性生产

目标：能灰度、能回滚、能承载 100+ 终端并发。

交付：

- Kubernetes 部署 API gateway、Agent runtime、RAG service、model gateway、model runtime。
- Argo Rollouts canary/blue-green。
- Model Gateway 支持按 tenant/user/header/percentage 灰度。
- Queue + fair scheduling + resource lease。
- SBOM、SLSA provenance、镜像签名和供应链扫描。
- red-team eval suite 和 rollback drill。

## 180-365 天：逼近安全关键成熟度

目标：从工程可用走到组织可治理。

交付：

- 多租户隔离和数据分级。
- 灾备演练、备份恢复演练和事故响应演练。
- 模型/Workflow/RAG 联动灰度。
- 合规证据包自动导出。
- 供应商依赖和开源组件的周期性审计。

## 项目内落地点

- `industrial_maturity_plan`：输出成熟度评分、CTO 拷问证据包、路线图和非协商门禁。
- `enterprise_stack_plan`：输出企业技术栈、热迭代、vLLM/SGLang 和 100+ 终端方案。
- `model_runtime_status`：模型服务可观测入口。
- `workflow_validate` / `workflow_dry_run`：执行前校验和预演。
- `evidence_ledger`：证据、训练和审计底座。
- `solution_publish`：成功 run 变成可复用方案资产。

## 参考框架

- NIST AI RMF：AI 风险治理的 govern / map / measure / manage 思路。
- NIST SSDF SP 800-218：安全软件开发实践。
- NIST SP 800-53：安全与隐私控制目录。
- SLSA：供应链 provenance 和构建完整性等级。
- OpenTelemetry：统一 traces、metrics、logs。
- Kubernetes / Argo Rollouts：弹性和渐进式发布。
