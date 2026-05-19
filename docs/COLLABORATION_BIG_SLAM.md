# 大满贯协作手册

本项目按“就业、竞赛、论文”三线同源推进：底座是同一个 Project Intelligence Agent，分别包装成工程作品、竞赛方案和论文实验。

## 三条长期分支

| 分支 | 负责人 | 目标 |
| --- | --- | --- |
| `feature/server-safe-jobs` | A：服务器/工程平台 | 服务器长期运行、资源约束、日志、状态观测、部署文档 |
| `feature/agent-project-reading` | B：主链路 Agent | 项目理解报告、RAG、证据引用、满意后入库、安全防注入 |
| `feature/github-model-eval-flywheel` | C：数据/模型/评价 | GitHub 数据分流、训练包、DeepSeek 微调/蒸馏、benchmark、论文实验 |

## 目录责任边界

### A：服务器与企业化

主要负责：

```text
agent/corpus_intelligence/cli.py
agent/corpus_intelligence/scheduler.py
agent/corpus_intelligence/flywheel.py
agent/corpus_intelligence/status.py
scripts/
deploy/
docs/DEPLOYMENT.md
docs/OPERATIONS.md
```

验收命令：

```bash
python -m agent.corpus_intelligence.cli status --output-root .runtime/corpus
python -m agent.corpus_intelligence.cli flywheel --output-root .runtime/corpus --repo-limit 3 --cpu-thread-budget 2
python -m pytest tests/test_corpus_cli.py tests/test_corpus_scheduler.py tests/test_corpus_flywheel.py tests/test_corpus_status.py -q
```

### B：Agent 主链路

主要负责：

```text
agent/core/
agent/chains/research.py
agent/chains/research_types.py
agent/chains/research_cache.py
agent/learning/
agent/prompts/
examples/
```

验收重点：

- 输入本地项目或 GitHub 项目，生成项目理解报告。
- 报告包含项目用途、架构、核心模块、风险、改进建议。
- 关键结论有 evidence。
- 用户未点满意时，不进入长期方案库。
- evidence block 内的指令不能覆盖系统指令。

建议测试：

```bash
python -m pytest tests/test_research*.py tests/test_executor.py tests/test_feedback.py -q
```

### C：数据、模型与论文实验

主要负责：

```text
agent/corpus_intelligence/ranking.py
agent/corpus_intelligence/projectization.py
agent/corpus_intelligence/training_bundle.py
agent/corpus_intelligence/feedback.py
agent/project_model/
agent/chains/model_training.py
experiments/
docs/MODEL_EVAL_AND_RELATED_WORK.md
```

验收重点：

- GitHub repo 质量评分可解释。
- 数据可分流到 `train_now` / `distill_pool` / `benchmark_holdout` / `reject`。
- `benchmark_holdout` 不进入训练集。
- 每条训练数据记录来源、license、route、label reason。
- 输出 metrics 和 feedback deltas。

建议测试：

```bash
python -m pytest tests/test_corpus_projectization.py tests/test_corpus_training_bundle.py tests/test_model_benchmark.py tests/test_model_training.py -q
```

## PR 规则

1. 每个 PR 只解决一个清晰问题。
2. PR 必须写明：做了什么、怎么测、影响范围、下一步。
3. 不提交大数据、模型权重、cache、`.runtime/`、token、私钥。
4. 新增 action 必须同步：
   - `agent/core/protocol.py`
   - `agent/core/executor.py`
   - tests
   - docs
5. 修改别人责任区前，先在 issue/PR 里说明原因。

## 大满贯交付物

### 就业

```text
README.md
docs/ARCHITECTURE.md
docs/DEPLOYMENT.md
docs/OPERATIONS.md
docs/RESUME_STORY.md
examples/demo_project_reading/
```

### 竞赛

```text
docs/COMPETITION_SUBMISSION.md
experiments/reports/
examples/sample_reports/
scripts/make_release_package.sh
```

### 论文

```text
docs/PAPER_OUTLINE.md
docs/MODEL_EVAL_AND_RELATED_WORK.md
experiments/baselines/
experiments/ablations/
experiments/reports/
```
