# DeepSeek 本地部署指南

本指南介绍如何在本地部署 DeepSeek 模型来替代默认的生产用 codex。

## 📋 前置要求

### 硬件要求
- **CPU**: x86_64 架构
- **内存**: 至少 32GB RAM
- **GPU**: NVIDIA GPU with CUDA 11.8+ (推荐)
  - DeepSeek-V3: 至少 128GB VRAM
  - DeepSeek-V2.5: 至少 48GB VRAM
  - DeepSeek-Coder-V2: 至少 48GB VRAM

### 软件要求
- Python 3.8+
- CUDA 11.8+ (如果使用GPU)
- 稳定的网络连接（用于下载模型）

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 DeepSeek 服务

#### Windows
```cmd
scripts\start_deepseek.bat
```

#### Windows / 6GB 显存或 CPU 轻量部署

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
python scripts/serve_deepseek_transformers.py --model deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B --host 127.0.0.1 --port 8000
```

该模式使用 Transformers 暴露 OpenAI-compatible `/v1/chat/completions`，适合 vLLM 不可用或显存不足的开发机。CPU 可运行但生成较慢。

#### Linux/Mac
```bash
python scripts/deploy_deepseek.py
```

### 3. 验证部署

服务启动后，访问以下地址验证：
- 健康检查: http://127.0.0.1:8000/health
- 模型列表: http://127.0.0.1:8000/v1/models
- API文档: http://127.0.0.1:8000/docs (如果支持)

## ⚙️ 高级配置

### 选择不同模型

```bash
# 使用 DeepSeek-V3 (默认，性能最强)
python scripts/deploy_deepseek.py --model deepseek-ai/DeepSeek-V3

# 使用 DeepSeek-V2.5 (中等规模)
python scripts/deploy_deepseek.py --model deepseek-ai/DeepSeek-V2.5

# 使用 DeepSeek-Coder-V2 (代码专用)
python scripts/deploy_deepseek.py --model deepseek-ai/DeepSeek-Coder-V2
```

### 自定义端口和地址

```bash
python scripts/deploy_deepseek.py --host 0.0.0.0 --port 8080
```

### GPU内存优化

```bash
# 调整GPU内存利用率 (0.0-1.0)
python scripts/deploy_deepseek.py --gpu-memory 0.8
```

### 多GPU并行

```bash
# 使用2个GPU进行张量并行
python scripts/deploy_deepseek.py --workers 2
```

## 🔧 环境变量配置

部署成功后，脚本会自动更新 `.env.local` 文件：

```bash
MAIN_DEEPSEEK_BASE_URL=http://127.0.0.1:8000/v1
MAIN_DEEPSEEK_MODEL=deepseek-ai/DeepSeek-V3
MAIN_DEEPSEEK_API_KEY=dummy
```

## 🧪 测试集成

先确认服务是否已经运行：

```bash
curl http://127.0.0.1:8000/health
```

如果无法连接，说明仓库只有部署脚本和 provider 接入，模型服务还没有实际启动。

### 1. 测试 Agent 集成

```bash
# 使用本地 DeepSeek 进行软件生产
python -m agent.main --llm --provider main_deepseek --goal "创建一个简单的 Flask API"

# 查看可用模型
python -c "from agent.llm.providers import provider_choices_for_ui; import json; print(json.dumps(provider_choices_for_ui(), indent=2))"
```

### 2. 手动测试 API

```bash
# 测试聊天完成
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "deepseek-ai/DeepSeek-V3",
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "max_tokens": 100
  }'
```

## 🧬 微调训练分链

项目内置 `training_prepare` action，用于准备 DeepSeek/代码模型微调前的数据资产。它只生成数据集、质量报告和训练计划，不会自动启动 GPU 训练。

```json
{"type":"action","action":"training_prepare","args":{"output_dir":"./training_runs/demo","learning_dirs":["./learning_runs/demo"],"solution_dirs":["./product_runs"],"dataset_format":"messages","eval_ratio":0.15,"model_hint":"deepseek-coder"}}
```

输出目录包含：

- `dataset.jsonl`
- `train.jsonl`
- `eval.jsonl`
- `raw_examples.jsonl`
- `quality_report.json`
- `training_plan.json`
- `report.md`

推荐实际训练流程：

1. 人工审查 `quality_report.json` 和样本内容，确认没有密钥、隐私数据和许可证风险。
2. 使用 LLaMA-Factory、Axolotl 或 TRL/SFTTrainer 执行 LoRA/QLoRA SFT。
3. 在独立评测集上验证 action JSON 合法率、RAG 引用忠实度和生产任务成功率。
4. 使用 vLLM 或兼容服务部署合并模型或 LoRA adapter。

## 🛠️ 故障排除

### 常见问题

#### 1. CUDA 相关错误
```
RuntimeError: CUDA out of memory
```
**解决方案**:
- 减少 `--gpu-memory` 参数值
- 使用更小的模型 (V2.5 替代 V3)
- 检查 GPU 内存是否充足

#### 2. 模型下载失败
```
HTTPError: 403 Client Error
```
**解决方案**:
- 检查网络连接
- 使用代理或VPN
- 手动下载模型文件到缓存目录

#### 3. 服务启动超时
```
服务启动超时
```
**解决方案**:
- 增加等待时间 (修改脚本中的超时设置)
- 检查 GPU 驱动和 CUDA 版本
- 查看详细日志输出

#### 4. 端口占用
```
OSError: [Errno 48] Address already in use
```
**解决方案**:
- 使用不同端口: `--port 8080`
- 停止占用端口的服务

### 查看日志

服务启动时会显示详细日志，帮助诊断问题：

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### 停止服务

在终端中按 `Ctrl+C` 停止服务，或使用：

```bash
# 查找进程
ps aux | grep vllm

# 停止进程
kill -9 <PID>
```

## 📊 性能优化

### 推理优化

1. **量化**: 使用 AWQ 或 GPTQ 量化减少内存占用
2. **FlashAttention**: 启用 FlashAttention 加速注意力计算
3. **连续批处理**: 启用 continuous batching 提高吞吐量

### 内存优化

1. **模型分片**: 将大模型分割到多个 GPU
2. **CPU offload**: 将部分计算 offload 到 CPU
3. **动态批处理**: 根据负载动态调整批处理大小

## 🔄 更新和维护

### 更新模型

```bash
# 停止当前服务
# 重新运行部署脚本，vLLM 会自动下载最新版本
python scripts/deploy_deepseek.py
```

### 备份配置

重要文件备份：
- `.env.local` (环境变量)
- `scripts/deploy_deepseek.py` (部署脚本)
- 模型缓存目录 (通常在 `~/.cache/huggingface/`)

## 📞 支持

如果遇到问题，请：

1. 检查本文档的故障排除部分
2. 查看 vLLM 官方文档: https://docs.vllm.ai/
3. 在项目中提交 Issue

## 📈 性能基准

| 模型 | 上下文长度 | 生成速度 | 内存占用 |
|------|-----------|---------|---------|
| DeepSeek-V3 | 32K | ~50 tok/s | 128GB+ |
| DeepSeek-V2.5 | 32K | ~80 tok/s | 48GB+ |
| DeepSeek-Coder-V2 | 16K | ~75 tok/s | 48GB+ |

*基准数据基于 A100 GPU，实际性能因硬件而异*
