# AGENTS.md

本文件用于指导人类贡献者与自动化 Agent（例如 Cursor/CI Bot）在本仓库内一致地工作：如何安装依赖、运行检查、提交变更，以及应遵守的约定。

## 项目概览

- **项目名**：Pallas-Bot
- **语言/运行时**：Python **3.12**
- **依赖管理**：`uv`
- **主要代码目录**：`src/`
- **质量门禁（CI）**：Ruff lint + Ruff format（见 `.github/workflows/ci.yml`）

## 本地开发快速开始

安装依赖（含开发依赖）：

```bash
uv sync --dev
```

运行 Ruff（与 CI 保持一致）：

```bash
uv run ruff check src/
uv run ruff format --check src/
```

如果需要自动修复与格式化：

```bash
uv run ruff check --fix src/
uv run ruff format src/
```

运行测试（如仓库包含 `tests/`）：

```bash
uv run pytest
```

## pre-commit（提交前检查）

本仓库提供 pre-commit hooks（见 `.pre-commit-config.yaml`），用于在提交前自动执行基础检查与 Ruff。

当前策略采用**细颗粒度分层**：

- **基础仓库检查覆盖全仓**：例如 YAML/TOML 语法、尾随空格、混合换行、文件结尾换行等。
- **Ruff 仅检查 `src/`**：避免对文档、脚本、编辑器配置等非主代码目录施加 Python lint/format。
- **`.env` 被全局排除**：避免本地敏感配置被 hooks 读取或改写。

首次安装 hooks：

```bash
uv run pre-commit install
```

手动对全仓运行：

```bash
uv run pre-commit run -a
```

仅运行 `src/` 代码检查时，可直接执行：

```bash
uv run ruff check src/
uv run ruff format --check src/
```

> 说明：如果你没有安装 `pre-commit`，可用 `uv add --dev pre-commit` 添加到开发依赖组后再运行。

## Agent 工作约定

### 修改范围

- **优先修改 `src/` 与 `tests/`**，避免无意义的重排/大范围格式变化。
- **不提交密钥与私密配置**：例如 `.env`、token、私钥、访问凭据等。
- **依赖变更需谨慎**：新增依赖优先走 `pyproject.toml`（`uv` 工作流），并确保 CI 仍能通过。

### 代码质量与风格

- **Ruff 是唯一强制的 lint/format 工具**（与 CI/预提交一致）。
- **pre-commit 的基础文件卫生检查覆盖全仓，但 Ruff 只针对 `src/`。**
- 提交前确保：
  - `uv run ruff check src/` 通过
  - `uv run ruff format --check src/` 通过

### 提交与 PR

- **一个 PR 只解决一类问题**（功能/修复/重构/文档不要混杂）。
- 提交信息建议采用：
  - `feat:` 新功能
  - `fix:` 修复
  - `refactor:` 重构（不改变外部行为）
  - `chore:` 构建/工具链/依赖
  - `docs:` 文档

## pre-commit.ci

仓库包含 `.pre-commit-ci.yaml`，用于开启 pre-commit.ci：

- 按较低频率自动更新 hooks 版本（当前为 `quarterly`）
- 在 PR 上自动应用可自动修复的变更（例如格式化、部分 lint autofix）
- 使用中文自动更新提交信息，便于与仓库日常提交风格保持一致

启用方式：

1. 在 GitHub 上安装/启用 pre-commit.ci（对该仓库授权）
2. 确保仓库根目录包含：
   - `.pre-commit-config.yaml`
   - `.pre-commit-ci.yaml`
