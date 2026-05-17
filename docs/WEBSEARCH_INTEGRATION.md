# WebSearch 集成说明

## 概述

WebSearch 功能已集成到软件生产 Agent 的默认生产环境中。Agent 可以使用 `web_search` action 查询外部网络信息，也可以使用更高层的 `research_synthesize` action 将 Web Search 与本地方案库、RAG 和大模型综合串起来。

## 功能特性

### web_search Action

**描述**: 使用 DuckDuckGo Instant Answer API 进行网络搜索

**协议**:
```json
{"type":"action","action":"web_search","args":{"query":"搜索词","top_k":5,"provider":"duckduckgo"}}
```

**参数**:
- `query` (必需): 搜索关键词 (字符串)
- `top_k` (可选): 返回结果数，默认 5 (正整数)
- `provider` (可选): 搜索提供商，目前支持 "duckduckgo"，默认 "duckduckgo" (字符串)

**返回值**:
```json
{
  "ok": true,
  "action": "web_search",
  "query": "搜索词",
  "results": [
    {
      "title": "结果标题",
      "url": "https://example.com",
      "snippet": "结果摘要",
      "source": "duckduckgo|fallback"
    }
  ],
  "count": 3
}
```

### research_synthesize Action

**描述**: 本地方案库优先，融合工作区/学习库 RAG，可选 Web Search 补充，可选 LLM 生成带引用方案。

**协议**:
```json
{"type":"action","action":"research_synthesize","args":{"query":"员工审批管理系统 Spring Vue CRUD","top_k":4,"solution_dirs":["./product_runs/solution_library"],"learning_dirs":["./learning_runs/demo"],"use_web":true,"use_llm":true,"llm_provider":"deepseek"}}
```

**证据优先级**:

1. `[S]` 已验收正式方案库：`solution_manifest.json` + `docs/SOLUTION_BACKUP.md`
2. `[R]` 本地工作区与学习库 RAG：代码、文档、知识卡索引
3. `[W]` Web Search：外部文档、最新 API、开源示例链接
4. LLM 综合：只根据上述证据输出方案，证据不足时明确说明

默认 `use_web=false`、`use_llm=false`，因此离线可跑；需要外部信息或大模型综合时显式打开。

## Agent 使用场景

### 1. 本地方案库 + Web + LLM 综合

```json
{"type":"action","action":"research_synthesize","args":{"query":"基于历史方案设计员工审批管理系统","solution_dirs":["./product_runs/solution_library"],"use_web":true,"use_llm":true,"llm_provider":"deepseek"}}
```

### 2. 查询最新的技术文档

```json
{"type":"action","action":"web_search","args":{"query":"Python 3.13 新特性","top_k":3}}
```

### 3. 查询开源项目

```json
{"type":"action","action":"web_search","args":{"query":"FastAPI OAuth 实现","top_k":5}}
```

### 4. 查询 API 文档

```json
{"type":"action","action":"web_search","args":{"query":"DuckDuckGo API 文档","top_k":3}}
```

### 5. 查询最佳实践

```json
{"type":"action","action":"web_search","args":{"query":"Python 项目结构最佳实践","top_k":4}}
```

## 系统提示

Agent 系统提示已更新，包含以下指导：

- web_search 可用于查询外部知识、API 文档、最新技术方案
- research_synthesize 用于“本地方案库 + RAG + Web + LLM”的综合研究
- 避免在可用 mcp_call、RAG 或 research_synthesize 时冗余调用 web_search
- 优先使用本地资源（读文件、RAG 检索）

## 使用建议

### ✅ 适合使用 web_search

- 查询外网不可用的最新技术信息
- 查找特定库的 API 文档链接
- 搜索开源项目或示例代码
- 获取第三方服务的接入指南
- 已有方案库证据不足，需要外部文档补齐

### ❌ 不适合使用 web_search

- 工作区内已有的信息（用 read_file/list_files）
- RAG 系统已索引的知识（用 mcp_call workspace.search）
- 需要综合本地方案库和外部资料（用 research_synthesize）
- 需要详细内容分析的情况（直接 read_file 更准确）

## 集成文件

以下文件已更新以支持 web_search：

1. **agent/core/executor.py**
   - 添加 web_search action 执行逻辑
   - 导入 search_web 函数

2. **agent/core/protocol.py**
   - 将 "web_search" 添加到 ALLOWED_ACTIONS
   - 添加 web_search 参数验证逻辑

3. **agent/prompts/action.txt**
   - 记录 web_search action 的协议定义

4. **agent/prompts/system.txt**
   - 添加 web_search 使用指导原则
   - 添加 research_synthesize 本地优先指导原则

5. **agent/chains/research.py**
   - 添加方案库/RAG/Web/LLM 综合分链

## 测试验证

运行以下命令验证 web_search 功能：

```bash
python test_web_search.py
```

## 性能考虑

- **响应时间**: ~2-20 秒（取决于网络连接）
- **结果质量**: 基于 DuckDuckGo Instant Answer，可能返回 fallback 链接
- **调用频率**: 无官方限制，建议合理使用

## 未来改进方向

1. **多源支持**: 集成 Tavily、Brave Search 等提供商
2. **内容抓取**: 自动获取搜索结果的完整网页内容
3. **结果排序**: 按相关性、新鲜度、信任度排序
4. **缓存优化**: 缓存频繁搜索的结果
5. **方案库评分**: 将用户反馈、交付结果和质量门禁结果反向写入方案库评分

## 故障排除

### 返回 fallback 链接

如果搜索结果返回 fallback（通用链接）而不是具体结果，可能原因：
- DuckDuckGo API 暂时不可用
- 网络连接问题
- 查询词不够具体

**解决方案**: 
- 修改搜索关键词提高具体性
- 增加 top_k 参数获取更多 fallback 链接

### 网络超时

如果搜索请求超时（timeout=20秒）：

**解决方案**:
- 检查网络连接
- 简化搜索词
- 稍后重试
