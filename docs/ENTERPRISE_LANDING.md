# Enterprise Landing Plan

这份文档回答三类上市企业级私有化落地问题，并对应 `enterprise_stack_plan` action 的结构化输出。

## 1. vLLM 与 SGLang 选型

### 结论

- **通用生产推理入口优先 vLLM**：适合高并发 API、OpenAI-compatible 服务、多 GPU、量化、生产运维。
- **结构化 Agent 与复杂前缀复用优先 SGLang**：适合多 Agent 工具调用、结构化 JSON、共享系统提示词、复杂 prompt program。
- **企业平台边界统一到 model gateway**：Agent 不直接绑定 vLLM 或 SGLang，只访问 `/v1/chat/completions`、`/v1/models` 和健康探测。

### 高并发 API 请求

推荐：

- vLLM 模型池服务短/中上下文 API。
- 按租户和任务类型做限流。
- short-context、long-context、agent-json 三类请求拆池。
- 用 TTFT、inter-token latency、queue time、GPU memory、KV cache hit 做容量指标。

核心配置：

- `--gpu-memory-utilization` 控制显存水位，常见从 `0.80-0.92` 压测起步。
- `--tensor-parallel-size` 按模型大小和 GPU 数量设置。
- `--max-model-len` 不盲目设最大，按业务真实 token 上限给。
- prefix caching 复用系统提示词、政策文本和固定 RAG 前缀。
- max batched tokens / max running sequences 通过压测确定，不靠默认值上生产。

### 32K+ 超长上下文

长上下文的真正瓶颈通常不是“能不能塞进 32K”，而是 prefill、KV cache、排队和短请求被长请求饿死。

落地策略：

- 长上下文单独模型池。
- 启用 chunked prefill，避免长 prefill 阻塞短请求。
- RAG 做分层召回：先 query rewrite / routing，再召回摘要，再按需展开原文。
- 对企业固定制度、API 契约、系统提示词做 prefix cache 预热。
- 设置 admission control：`max_input_tokens`、`max_output_tokens`、tenant QPS、并发槽位。

### SGLang 专项场景

适合：

- 多 Agent 工具调用。
- 强 JSON/grammar 结构化输出。
- 共享前缀很多的 prompt program。
- Agent 工作流中需要大量受约束输出。

配置关注：

- `max_running_requests`
- `max_total_tokens`
- chunked prefill / max prefill tokens
- structured outputs / grammar
- queue time、TTFT、ITL 指标

## 2. 生产级多 Agent 工程治理

### 外部 API 依赖

解决：

- 所有外部 API 经 tool gateway。
- tool gateway 负责 timeout、retry、circuit breaker、fallback、audit。
- API 分 critical 和 optional；optional 失败只降级，不阻断主链。
- Web Search 只能作为补充证据，必须经过 evidence arbiter。
- 所有第三方 API 做 contract test 和 mock/sandbox。

项目对应：

- `protocol.py`：只允许白名单 action。
- `executor.py`：唯一执行入口。
- `research_synthesize`：本地方案/RAG 优先，Web 只补充。
- `evidence_ledger`：沉淀来源、评价和风险。

### 多 Agent 任务争抢

解决：

- Agent 不直接抢 GPU、文件、爬虫槽位和训练槽位。
- 所有任务进入 workflow executor 或 queue。
- 用 resource lease 管理 GPU slot、repo clone slot、training slot、crawler slot。
- 按 tenant/project/run_id 做公平队列和优先级。
- 写文件必须走 workspace guard 和 manifest。

推荐栈：

- Kafka / Redis Stream：任务队列。
- PostgreSQL：job、lease、run、audit 状态。
- OpenTelemetry：贯穿 Agent loop、tool gateway、model gateway。

### 上下文膨胀

解决：

- 每轮只给 `context_digest`，不把完整历史塞回模型。
- RAG 片段必须带 path、line、score、source 和 token budget。
- 长会话分三类摘要：decision summary、evidence summary、artifact summary。
- 训练数据只从 evidence ledger 和高质量 manifest 中筛选。

项目对应：

- `agent/context/digest.py`
- `agent/rag/unified.py`
- `agent/evidence/ledger.py`
- `agent/chains/training.py`

## 3. 100+ 终端私有化 AI 平台

### 模型版本管理

要管理的不只是模型权重，还包括：

- base model
- LoRA/adapter
- quantization
- prompt template
- tool schema
- Agent workflow version
- RAG index version
- eval score
- rollout stage

每次请求记录：

- `model_version`
- `workflow_version`
- `rag_index_version`
- `run_id`
- `tenant_id`

门禁：

- action JSON 合法率
- RAG 引用忠实度
- p95 latency
- 安全和越权测试
- 成本/token 预算

### 灰度发布

服务级：

- Kubernetes rolling update 做基础滚动。
- Argo Rollouts 做 canary / blue-green。

模型级：

- model gateway 支持按 tenant、user、header、percentage 路由。
- 新模型先 shadow traffic，再 1%-5% canary。
- 失败自动回滚到 stable model。

RAG 级：

- active/candidate 双索引。
- candidate 召回差异进入 evaluation report。
- 不能直接覆盖生产索引。

Agent 级：

- workflow.v1 版本化。
- 新 workflow 先 dry-run，再 shadow，再 canary。
- feature flag 控制 workflow_executor、model_router、training_pipeline、web_search。

### 弹性扩缩容

分层部署：

```text
API Gateway
  -> Agent Runtime
  -> Workflow Executor / Queue
  -> RAG Service
  -> Model Gateway
  -> vLLM / SGLang / Transformers model pools
```

扩缩容指标：

- API/RAG：CPU、QPS、p95 latency。
- Agent runtime：queue depth、running jobs、tool error rate。
- Model runtime：TTFT、ITL、GPU utilization、KV cache pressure、queue time。
- GPU 节点：Karpenter / Cluster Autoscaler。

100+ 终端起步配置：

- API gateway：2 replicas 起。
- Agent runtime：2-3 replicas 起。
- RAG service：2 replicas 起。
- Model gateway：2 replicas 起。
- Model runtime：短上下文池 + 长上下文池至少分开。

## 项目内落地点

- `enterprise_stack_plan`：输出企业技术选型、热迭代、模型服务、多 Agent 治理和三大场景解决方案。
- `model_runtime_status`：检查本地/兼容模型服务。
- `resource_registry`：发现 model provider、model runtime、solution、knowledge、dataset、run manifest、evidence ledger。
- `workflow_validate` / `workflow_dry_run`：先校验和预演，再执行。
- `evidence_ledger`：作为审计、训练筛选、事故回放的证据底座。

## 参考

- vLLM docs: <https://docs.vllm.ai/>
- SGLang docs: <https://docs.sglang.ai/>
- Kubernetes docs: <https://kubernetes.io/docs/>
- Argo Rollouts docs: <https://argo-rollouts.readthedocs.io/>
- OpenTelemetry docs: <https://opentelemetry.io/docs/>
