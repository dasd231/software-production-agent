# RAG链路深化改进

## 概述

本次改进深化了software-production-agent项目的RAG（Retrieval-Augmented Generation）链路，增强了检索质量、回答生成和置信度评估。

## 主要改进

### 1. 向量存储增强
- **OpenAI Embedding支持**：在`vector_store.py`中添加了OpenAI text-embedding-3-small模型支持
- **灵活配置**：支持切换hashing vector和OpenAI embedding
- **向后兼容**：保持原有hashing vector作为默认选项

### 2. 检索融合
- **BM25检索**：添加了基于词频的BM25检索算法
- **结果融合**：将向量搜索和BM25结果融合，去重排序
- **依赖管理**：添加rank-bm25包到requirements.txt

### 3. 生成式回答
- **LLM集成**：集成项目现有的LLM提供者（OpenAI、Groq、DeepSeek）
- **上下文构建**：基于检索到的知识卡和代码证据生成答案
- **错误处理**：LLM失败时自动回退到抽取式答案

### 4. 置信度评估
- **多维度评估**：基于分数差距、证据数量、卡片覆盖率计算置信度
- **标准化输出**：在回答结果中包含confidence字段

## API变更

### answer_question函数签名
```python
def answer_question(
    question: str,
    vector_index: VectorIndex,
    cards: list[KnowledgeCard],
    *,
    top_k: int = 4,
    use_bm25: bool = False,
    use_generative: bool = False,
    llm_provider: str = "openai",
    llm_model: str = None,
) -> dict[str, object]:
```

### 新增参数
- `use_bm25`: 启用BM25检索融合
- `use_generative`: 启用生成式回答
- `llm_provider`: 指定LLM提供者
- `llm_model`: 指定LLM模型

### 返回值增强
- 新增`confidence`字段：0-1之间的置信度分数

## 使用示例

```python
# 基础抽取式回答
result = answer_question("如何安装项目？", vector_index, cards)

# 启用检索融合
result = answer_question("项目架构是什么？", vector_index, cards, use_bm25=True)

# 生成式回答
result = answer_question("解释这个算法", vector_index, cards, use_generative=True, llm_provider="deepseek")

# 完整配置
result = answer_question(
    "代码质量如何？", 
    vector_index, 
    cards, 
    use_bm25=True, 
    use_generative=True, 
    llm_provider="groq", 
    llm_model="llama-3.1-8b-instant"
)
```

## 性能考虑

- OpenAI embedding需要API密钥和网络访问
- BM25检索增加计算开销，但提升检索质量
- 生成式回答依赖LLM API，可能增加延迟
- 置信度计算轻量级，不影响性能

## 测试验证

所有现有测试通过，确保向后兼容性。新增功能通过参数控制，默认保持原有行为。

## 未来扩展点

1. **ANN索引**：集成FAISS或HNSW进行近似最近邻搜索
2. **混合检索**：添加更多检索方法（如语义搜索、图搜索）
3. **答案评估**：基于用户反馈的答案质量评估
4. **多语言支持**：支持非英语查询的检索和生成