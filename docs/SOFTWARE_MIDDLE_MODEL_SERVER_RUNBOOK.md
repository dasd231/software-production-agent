# Software Middle Model First Server Training Runbook

> 目标：把中间层小模型第一批 smoke training 安全地跑上服务器。  
> 注意：bootstrap 生成的是种子 trace，只用于打通训练链路，不代表最终模型质量。

## 1. 服务器拉代码

```bash
cd /data/ThreadModel/projects

# 如果还没有仓库
git clone git@github.com:dasd231/software-production-agent.git

cd software-production-agent
git fetch origin
git switch feature/software-middle-model
git pull
```

## 2. 生成第一批训练包

```bash
python -m agent.software_middle_model.cli bootstrap-first-round \
  --output-root /data/ThreadModel/software_middle_first \
  --min-traces 8 \
  --adapter-name software-middle-model-lora \
  --max-seq-length 1024 \
  --cpu-threads 4 \
  --max-gpu-memory-gb 12
```

生成目录：

```text
/data/ThreadModel/software_middle_first/
  middle_model/traces.jsonl
  training_runs/software-middle-first/
  model_runs/software-middle-first/
```

## 3. 看交接说明

```bash
cat /data/ThreadModel/software_middle_first/model_runs/software-middle-first/SERVER_HANDOFF.md
```

## 4. 检查 GPU 是否空闲

```bash
nvidia-smi
```

如果看到别人有 compute process，不要启动训练。

## 5. 先 dry-run

```bash
python -m agent.training.backup_trainer \
  --config /data/ThreadModel/software_middle_first/model_runs/software-middle-first/backup_training_spec.json \
  --dry-run
```

如果 dry-run 报缺依赖，先装依赖或切到正确 conda 环境。

## 6. 真正启动训练

只有在 GPU 空闲、dry-run 通过后运行：

```bash
python -m agent.training.backup_trainer \
  --config /data/ThreadModel/software_middle_first/model_runs/software-middle-first/backup_training_spec.json
```

也可以查看自动生成的命令：

```bash
cat /data/ThreadModel/software_middle_first/model_runs/software-middle-first/launch_command.txt
```

## 7. 训练完成后看结果

```bash
cat /data/ThreadModel/software_middle_first/model_runs/software-middle-first/report.md
cat /data/ThreadModel/software_middle_first/model_runs/software-middle-first/model_version_manifest.json
```

Adapter 默认输出到：

```text
/data/ThreadModel/software_middle_first/model_runs/software-middle-first/adapter
```

## 8. 停止规则

- GPU 有别人进程：停。
- dry-run 没过：停。
- 缺依赖：先修环境，不要硬跑。
- 服务器卡顿：停。
- 第一轮只验证链路，不追求效果。
