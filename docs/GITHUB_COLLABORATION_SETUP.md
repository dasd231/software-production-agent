# GitHub 协作设置

本仓库已经通过文件方式内置了：

- PR 模板
- Issue Forms
- 大满贯协作手册
- Roadmap
- CI 同时监听 `main` 和 `master`

由于当前环境没有安装 `gh` CLI，真实 GitHub Labels / Issues / Project Board 不能在本机直接创建。若要补齐 GitHub 页面上的 labels 和 starter issues，在已登录 GitHub CLI 的机器上运行：

```bash
python scripts/setup_github_collaboration.py --create-labels --create-issues
```

## 建议创建的 GitHub Project

名称：

```text
Project Intelligence Agent Roadmap
```

建议视图：

1. By Track：employment / competition / paper
2. By Area：infra / agent / data / model / eval / docs
3. By Milestone：M1-M5
4. By Assignee：A / B / C

## 建议 Milestones

```text
M1 Demo Ready
M2 Server Flywheel
M3 Competition Package
M4 Paper Draft
M5 Public Release
```

## 协作分支

```text
feature/server-safe-jobs
feature/agent-project-reading
feature/github-model-eval-flywheel
```
