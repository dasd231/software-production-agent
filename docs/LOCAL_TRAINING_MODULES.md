# 本地轻量训练模块：服务器前的训练闭环

> 目标：没有服务器时，先在本地 CPU 上把两个小模型的数据闭环、标签定义、坑点和透明 baseline 做出来。  
> 代码位置：`agent/local_training/`  
> Action：`local_training_run`

## 1. 两个模型

### 1.1 中间层小模型

目标：优化算法规则耗时。

```text
输入：任务特征 + 候选规则/路径 + 历史决策 trace
输出：是否可以 shortcut，还是必须回退执行费时规则
```

它不替代规则系统，而是做 **高频低风险场景的路由/判别**：

```text
低风险 + 高置信 + margin 足够 -> small_model_shortcut
高风险 / 低置信 / margin 小 -> run_expensive_rules
```

本地训练输出：

```text
middle_model_local.json
```

模型类型：透明 Logistic CPU baseline。

### 1.2 GitHub 爬虫评价模型

目标：优化 GitHub 项目爬取、筛选和入训质量。

```text
输入：repo ranking rows
特征：lexical_relevance / repo_quality / freshness / governance / novelty / downstream_utility
输出：是否 route 到 train_now / distill_pool，还是 observe / quarantine
```

本地训练输出：

```text
github_evaluator_local.json
```

## 2. Action 用法

```json
{
  "type": "action",
  "action": "local_training_run",
  "args": {
    "target": "both",
    "output_dir": "local-training-runs/demo",
    "middle_trace_paths": ["data/middle_traces.jsonl"],
    "github_ranking_paths": ["data/github_ranking.jsonl"],
    "epochs": 30
  }
}
```

权限：

```text
model:train + workspace:write
```

这个 action 是 high risk，需要确认，因为它会写训练产物。

## 3. 为什么先做本地训练

服务器训练前最容易踩坑：

```text
标签定义不清
训练目标和线上决策不一致
质量指标没进闭环
为了省 latency 牺牲安全
GitHub 样本被 stars/popularity 带偏
license/governance 被软化成模型偏好
```

所以本地先做：

```text
透明特征
透明标签
透明 baseline
透明坑点
小数据闭环
```

等本地标签和 hard gate 稳了，再上服务器做 LoRA/SFT/更复杂模型。

## 4. 企业化要求

- 高风险任务永远保留 expensive rule fallback；
- license/governance 是 hard gate，不交给模型自由学习；
- GitHub 数据要记录证据来源、README/测试/入口文件、许可协议；
- 中间层小模型的收益必须同时看 latency_saved_ms 和 quality_delta；
- 训练结果要进入 scorecard，不允许只报 accuracy。

## 5. 面试讲法

> 我没有等服务器才开始做训练。我先把两个小模型的本地 CPU baseline 做出来：一个用于中间层规则加速，一个用于 GitHub 语料质量评价。重点不是模型多复杂，而是先把标签、特征、fallback、hard gate 和质量闭环设计对。这样后续上服务器训练 DeepSeek 开源模型或轻量 LoRA 时，训练目标不会跑偏。

---

## 6. 本轮升级：从“能训练”到“本地小模型闭环”

本轮把 `agent/local_training/` 从简单 baseline 升级成了一个可解释的小模型训练座舱：

```text
agent/local_training/
  schemas.py              # LocalTrainingExample / LocalModelArtifact / LocalPrediction
  feature_extraction.py   # 两个模型的特征契约与标签抽取
  trainer.py              # 透明 logistic CPU 训练、验证集评估、样本导出
  inference.py            # 本地推理与 hard gate 兜底
  sample_data.py          # 可演示的小样本数据生成
  cli.py                  # 本地命令行入口
```

### 6.1 中间层规则加速模型的特征

特征不再只有置信度，而是覆盖到了软件生产链路里的真实风险：

```text
confidence              模型/规则候选置信度
margin                  第一候选和第二候选差距
risk_signal             任务风险信号
candidate_count         候选证据/路径数量
latency_saved_ms        shortcut 可能节省的时间
quality_delta           shortcut 后质量变化
must_have_coverage      必要槽位覆盖率
guard_violation_rate    Skill Guard 违规密度
patch_risk              diff/patch 风险
human_override_signal   人工是否覆盖了模型判断
```

标签语义保持非常清楚：

```text
1 = 必须运行 expensive deterministic rules
0 = 可以允许 shortcut
```

注意：这个模型不是为了“绕过规则”，而是为了在低风险、高覆盖、高置信场景下减少中间层耗时。遇到安全、权限、支付、部署、删除、must_have 槽位缺失、Guard 违规时，仍然强制走规则兜底。

### 6.2 GitHub 项目质量评价模型的特征

GitHub 语料评价也升级成更贴近训练质量的特征：

```text
lexical_relevance       和目标任务的词面相关度
repo_quality            仓库工程质量
freshness               维护新鲜度
governance              治理质量
novelty                 新颖性/覆盖增益
downstream_utility      对后续检索/训练的实际帮助
test_signal             是否有测试
ci_signal               是否有 CI
license_signal          license 是否可用
architecture_depth      架构深度
security_signal         安全扫描/敏感信息风险
```

标签语义：

```text
1 = 可进入 train_now / distill_pool
0 = observe / quarantine
```

其中 license、secret scan、malware scan 是 hard gate：即使模型觉得分数高，只要治理失败也不能入训。

### 6.3 本地训练命令

生成演示数据：

```bash
python -m agent.local_training.cli make-demo-data --output-dir local_training_demo
```

训练两个模型：

```bash
python -m agent.local_training.cli train \
  --target both \
  --output-dir local_training_runs/demo \
  --middle-trace-path local_training_demo/demo_middle_traces.jsonl \
  --github-ranking-path local_training_demo/demo_github_rankings.jsonl \
  --epochs 30
```

输出产物：

```text
local_training_manifest.json       总清单 + 质量门禁
middle_model_local.json            中间层模型权重
middle_model_examples.jsonl        中间层训练样本
github_evaluator_local.json        GitHub 质量模型权重
github_evaluator_examples.jsonl    GitHub 训练样本
```

### 6.4 本地推理与 hard gate

模型推理不是裸概率输出，而是带 hard gate：

```python
from agent.local_training import load_local_model, classify_middle_decision, score_github_repo

middle_model = load_local_model("local_training_runs/demo", target="middle")
result = classify_middle_decision(middle_model, trace)

repo_model = load_local_model("local_training_runs/demo", target="github")
score = score_github_repo(repo_model, repo_row)
```

输出包含：

```text
probability             模型概率
label                   0/1 标签
decision                业务决策
features                实际使用的特征
hard_gate_triggered     是否触发硬门禁
hard_gate_reasons       触发原因
```

这点很关键：本地小模型永远不是“黑盒决定生产行为”，它只是给出建议；安全、license、must_have coverage、Guard 违规这些规则仍然保留最高优先级。

### 6.5 为什么这个设计适合后续服务器训练

服务器训练前最危险的是：还没想清楚标签和门禁，就直接烧 GPU。现在本地闭环已经固定了：

```text
数据结构 -> 特征抽取 -> 标签语义 -> 训练 -> 评估 -> hard gate -> 推理输出 -> 质量门禁
```

后续上服务器时，只需要替换模型体量：

```text
transparent logistic baseline
  -> LightGBM / 小型 MLP
  -> sentence-transformer + classifier
  -> DeepSeek 开源模型蒸馏/LoRA
```

但标签、特征、hard gate、质量报告不变。这就是本地模型模块的价值：它不是玩具训练，而是服务器训练前的控制面。

### 6.6 新增：服务器微调前的 SFT 导出

本地训练不直接烧 GPU，但会把稳定后的样本导出成服务器可用的 chat SFT JSONL：

```bash
python -m agent.local_training.cli export-sft \
  --training-dir local_training_runs/demo \
  --output-dir local_training_runs/demo_sft
```

输出：

```text
middle_model_sft.jsonl          中间层规则加速小模型 SFT 数据
github_evaluator_sft.jsonl      GitHub 语料评价小模型 SFT 数据
finetune_export_manifest.json   后续 DeepSeek/Qwen LoRA 训练建议
```

关键原则：

```text
本地 baseline 负责稳定标签、特征和 hard gate；
服务器 LoRA/SFT 只学习表达能力、泛化和复杂语义判断；
license、安全、must_have 覆盖率等 hard gate 仍由规则系统执行，不能交给模型覆盖。
```
