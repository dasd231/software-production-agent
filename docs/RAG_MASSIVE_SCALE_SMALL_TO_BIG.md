# 海量数据 RAG 链路升级：Small-to-Big 与元数据治理

本次升级目标不是再堆一个相似度检索，而是把 RAG 链路从“单层 chunk 检索”推进到“面向海量项目数据的可治理检索”。核心变化是：

```text
原始仓库 / GitHub 项目
  -> CodeSlice 子块
  -> ParentChunk 父块
  -> 子块向量索引
  -> small-to-big 召回扩展
  -> 带元数据的证据包
  -> Agent / 训练样本 / 评估统计
```

## 1. 为什么要做 small-to-big

传统做法是：

```text
query -> topK 相似 chunk -> 直接塞给模型
```

问题是：

- chunk 太小：命中精准，但上下文不够，模型不知道函数/类/模块边界。
- chunk 太大：上下文完整，但 embedding 噪声大，召回精度下降。
- 海量 GitHub 项目下，如果所有内容都大块建索引，成本和延迟都会被放大。

升级后的做法是：

```text
query
  -> 先检索小子块 child chunk
  -> 根据 parent_id 找到父块 parent chunk
  -> 给模型喂父块
```

也就是：

```text
小块负责“找得准”
父块负责“看得全”
```

## 2. 当前落点

新增模块：

```text
agent/learning/hierarchical_rag.py
```

核心能力：

```text
build_hierarchical_vector_index()
  构建 child vector index + parent chunk store

small_to_big_search()
  子块检索后扩展父块

expand_evidence_small_to_big()
  把已有证据从 child evidence 扩展为 parent evidence

save_hierarchy_artifacts()
  保存 parent chunks 和 hierarchy meta
```

离线学习流水线已经接入：

```text
agent/learning/orchestrator.py
```

运行 learning pipeline 后会额外生成：

```text
rag_parent_chunks.jsonl
rag_hierarchy_meta.json
```

原有文件仍保持：

```text
vector_index.jsonl
vector_meta.json
knowledge_cards.json
```

所以兼容旧链路，同时新增父子结构。

## 3. 元数据 schema

每条 child vector record 会写入明确 metadata：

```json
{
  "schema": "hierarchical_rag.v1",
  "granularity": "child",
  "repo_id": "learning_run",
  "path": "app/services/book_service.py",
  "path_parts": ["app", "services", "book_service.py"],
  "module_path": "app/services",
  "file_name": "book_service.py",
  "extension": ".py",
  "language": "python",
  "content_type": "code",
  "source_kind": "source_code",
  "start_line": 1,
  "end_line": 80,
  "line_count": 80,
  "token_count": 420,
  "symbol_hints": ["BookService", "borrow_book"],
  "framework_hints": ["fastapi", "pytest"],
  "parent_id": "parent:xxxx",
  "parent_start_line": 1,
  "parent_end_line": 240,
  "parent_token_count": 1200,
  "dedupe_key": "..."
}
```

这套 metadata 的作用是让 RAG 支持：

- 按语言过滤：Python / Java / Vue / Markdown
- 按内容类型过滤：code / documentation / test / configuration
- 按路径过滤：backend / frontend / docs / tests
- 按框架过滤：Spring / FastAPI / Vue / Docker / K8s
- 按 symbol 辅助召回：class / def / function / method
- 按 parent_id 做 small-to-big 扩展
- 按 dedupe_key 做离线去重

## 4. 海量数据侧怎么接 Spark

Spark 不直接负责模型训练，而负责离线 RAG 数据生产线：

```text
GitHub 原始项目
  -> Spark 清洗文件 / 过滤 license / 去重
  -> 生成 repo-level metadata
  -> 生成 file-level metadata
  -> 生成 child chunk / parent chunk
  -> 统计质量、覆盖率、重复率、活跃度
  -> 输出 parquet / jsonl
  -> Python 侧建向量索引或导入向量库
```

推荐离线表：

```text
repo_table
file_table
child_chunk_table
parent_chunk_table
evidence_quality_table
retrieval_eval_table
```

这样后续可以支撑：

- 大规模 GitHub 项目评价模型
- RAG 召回质量评估
- 训练数据筛选
- 低质量项目过滤
- 项目知识图谱构建

## 5. 与原 RAG 的差异

| 维度 | 原链路 | 新链路 |
|---|---|---|
| 切片 | 单层 CodeSlice | child + parent 双层 |
| 检索 | topK chunk | child topK -> parent expansion |
| 上下文 | 命中块原文 | 父块上下文 |
| metadata | path/language/line | schema/content_type/source_kind/symbol/framework/parent_id |
| 海量数据 | 较难过滤治理 | 可按 metadata 做离线批处理与在线过滤 |
| 评估 | 看命中 chunk | 可看 child 命中、parent 覆盖、证据质量 |

## 6. 面试讲法

可以这样讲：

> 我没有简单扩大 chunk size。因为大 chunk 会降低召回精度，小 chunk 又会让模型缺上下文。所以我做了 small-to-big：embedding 索引用小块保证精确命中，真正给模型的证据扩展到父块，保证代码/文档/模块语义完整。同时每条证据都有规范 metadata，后续 Spark 离线作业可以按 repo、path、language、content_type、framework、symbol 和 parent_id 做清洗、过滤、评估和训练样本构造。

一句话：

```text
小块召回，父块理解；metadata 治理，Spark 扩展。
```
