# Pallas-Bot 贡献指南

感谢你愿意为 `Pallas-Bot` 做贡献。

本指南用于统一 Issue / PR 提交流程，帮助你的修改更快被审阅和合并。

## 提交 Issue

提交前建议先搜索是否已有同类问题：<https://github.com/PallasBot/Pallas-Bot/issues>

### Bug 反馈

请尽量提供以下信息：

- 问题现象与预期行为
- 最小复现步骤
- 运行环境（系统、Python 版本、协议端、数据库后端）
- 日志或报错截图（脱敏后）

### 功能建议

建议描述：

- 你想解决的实际问题
- 期望行为
- 可选实现思路（如有）

### 文档改进

如果文档有过时、歧义或缺失，欢迎直接提 Issue 或 PR。

## Pull Request

### 分支与流程

- 请勿直接向 `main` 提交代码。
- 推荐从 `main` 拉取分支开发，再向 `main` 发起 PR。
- PR 建议保持“单一主题、最小改动”。

### 代码与目录约定

开始编码前建议先阅读：

- [项目结构约定](docs/architecture/project-structure.md)
- [插件目录约定](docs/architecture/plugin-convention.md)
- [Agent 协作约定](AGENTS.md)

### 本地开发环境

```bash
uv sync --dev
```

### 提交前检查

```bash
uv run ruff check src/
uv run ruff format --check src/
```

可选自动修复：

```bash
uv run ruff check --fix src/
uv run ruff format src/
```

如仓库包含测试，请运行：

```bash
uv run pytest
```

### pre-commit（推荐）

```bash
uv run pre-commit install
uv run pre-commit run -a
```

### Commit 建议

- 一个 commit 聚焦一件事
- 标题清晰表达意图
- 推荐前缀：`feat:` `fix:` `docs:` `refactor:` `chore:`

## 沟通方式

如果对贡献流程有疑问，可在 Issue 留言或加入 QQ 开发者群交流。

- QQ 开发者群：`716692626`
