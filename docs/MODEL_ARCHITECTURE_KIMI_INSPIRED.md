# Kimi-inspired Local Model Architecture Blueprint

> 位置：`agent/model_arch/`  
> 目的：参考 Kimi 开源模型公开设计中的长上下文、MoE/FFN、MLA、训练稳定性思想，转化成本项目“小模型/中间层模型”的可解释架构路线。不是复刻 Kimi，也不在本机训练超大模型。

## 参考来源

- MoonshotAI `Kimi-K2` GitHub：Kimi K2 是 MoE 架构，公开摘要中列出 1T 总参数、32B 激活参数、61 层、MLA、SwiGLU、128K context 等模型摘要。  
  https://github.com/MoonshotAI/Kimi-K2
- arXiv 技术报告 `Kimi K2: Open Agentic Intelligence`：摘要提到 MoE、MuonClip、QK-clip、15.5T tokens、agentic data synthesis 和 RL。  
  https://arxiv.org/abs/2507.20534

## 我们借鉴什么，不借鉴什么

借鉴：

1. 长上下文注意力要做稳定性治理，不只是扩大 window。
2. FFN/MoE 是能力容量核心，注意力负责跨 token 路由，残差负责防止表示被破坏。
3. QK/attention logit spike 是训练和压力场景下的风险，要监控或 clipping。
4. Agentic 能力不能只靠 base model，要有数据合成、环境交互、评测 harness。

不借鉴：

1. 不在本项目复刻 1T MoE；算力、数据、工程成本都不现实。
2. 不把“参考 Kimi”说成“实现 Kimi”。本项目落点是企业 AgentOS 的小模型与评测闭环。

## 当前实现

代码：`agent/model_arch/transformer_blueprint.py`

核心链路：

```text
RMSNorm
 -> Attention / MLA-like attention
 -> Attention Residual
 -> RMSNorm
 -> SwiGLU / MoE-like FFN
 -> FFN Residual
```

也保留实验链路：

```text
RMSNorm
 -> FFN
 -> FFN Residual
 -> RMSNorm
 -> Attention
 -> Attention Residual
```

为什么这样设计：

- **Attention**：解决长上下文、NeedSlot、Evidence、Graph path 之间的信息路由。
- **FFN / MoE**：负责非线性特征存储和任务能力扩展。
- **Residual**：防止注意力或 FFN 一次变换破坏原始表示。
- **RMSNorm + QK clip**：提升训练/推理稳定性，避免压力提示下注意力异常尖峰。

## 在本项目的真实用途

1. `middle_model_rule_acceleration`：判断是否跳过昂贵规则/图检索/语义检索。
2. `github_corpus_quality_evaluator`：对仓库证据卡做 attention pooling 后再判断是否入训练池。
3. `semantic_retrieval`：对 NeedSlot 和 CandidateEvidence 做 slot-aware attention。
4. `hallucination_harness`：把压力/诱惑失败样本作为训练和评测数据。

## 面试讲法

> 我参考 Kimi 这类开源 Agentic 模型时，不是说我要复刻它，而是吸收几个工程思想：长上下文注意力要稳定，FFN/MoE 是容量核心，残差保证深层网络可训练，QK clipping 这类稳定性手段要进入设计。我的项目里把这些思想转成本地小模型蓝图，用来服务中间层路由、GitHub 语料质量评价和语义检索，而不是盲目烧算力。
