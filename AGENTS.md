# AGENTS.md

本文件用于指导人类贡献者与自动化 Agent（例如 Cursor/CI Bot）在本仓库内一致地工作：如何安装依赖、运行检查、提交变更，以及应遵守的约定。

## 项目概览

- **项目名**：Pallas-Bot
- **语言/运行时**：Python **3.12**
- **依赖管理**：`uv`
- **主要代码目录**：`src/`
- **质量门禁（CI）**：Ruff lint/format + 依赖漏洞扫描 + Docker 构建校验（见 `.github/workflows/ci.yml`）

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

可选执行与 CI 对齐的补充检查：

```bash
uv run pip-audit
docker build -t test-build .
```

> 说明：`pip-audit` 在 CI 中采用“尽量报告不阻断”的策略（`|| true`），用于优先暴露风险而不是拦截合并；本地可先查看结果再决定修复节奏。

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

## 文档与排障入口

- **插件专项说明**：[docs/plugins/README.md](docs/plugins/README.md)（各子目录 `README.md` 与 `src/plugins/<name>/` 对应）。
- **命令权限（cmd_perm）**：[docs/common/cmd_perm/README.md](docs/common/cmd_perm/README.md)（可配置等级、WebUI 覆盖、帮助菜单「何人可用」）。
- **常见问题与部署排障**：[docs/FAQ.md](docs/FAQ.md)。

## Agent 工作约定

### 修改范围

- **优先修改 `src/` 与 `tests/`**，避免无意义的重排/大范围格式变化。
- **不提交密钥与私密配置**：例如 `.env`、token、私钥、访问凭据等。
- **依赖变更需谨慎**：新增依赖优先走 `pyproject.toml`（`uv` 工作流），并确保 CI 仍能通过。
- **最小必要改动**：只改完成任务所需的代码与文件；避免「顺手」重构无关模块、扩大 diff。
- **全仓格式化/尾随空格/无关换行**：非任务所需不要做；若某次检查或格式化会**波及大量历史文件**，先向维护者说明影响范围再执行。
- **历史问题**：若发现与本次任务无关的遗留问题，在说明中区分「历史遗留」与「本次引入」；不要默认在同一变更里大包大揽修复。

### 代码质量与风格

- **Ruff 是唯一强制的 lint/format 工具**（与 CI/预提交一致）。
- **pre-commit 的基础文件卫生检查覆盖全仓，但 Ruff 只针对 `src/`。**
- 提交前确保：
  - `uv run ruff check src/` 通过
  - `uv run ruff format --check src/` 通过
- **与周边代码一致**：命名、类型、抽象层次、导入风格、注释密度与文件内既有写法对齐；优先复用已有函数。
- **新增函数**：非必要**不要**以下划线 `_` 作为前缀。
- **注释**：保持精简；obvious 逻辑不必长段 docstring。

### 日志（NoneBot / loguru）

- 项目常用 **loguru 风格**的 `logger`（如 NoneBot 提供的 logger）。
- 占位符优先使用 **`{}`** 或整条 **f-string**，避免沿用标准库 `logging` 的 `logger.debug("msg %s", x)` 写法，以免消息中仍出现字面量 `%s`。

### 语言与协作文档

- 与维护者/PR 描述可用 **中文**；**代码标识符、配置键名、路径、命令** 保持仓库既有习惯（多为英文键名，勿强行翻译）。
- 修改 **配置、文档、CI/自动化** 时，可补充**简短注释**说明用途即可，不必在注释里长篇解释动机（动机放在 PR/对话里）。

### 插件命令权限与帮助文案（cmd_perm）

接入可配置命令权限的插件时：

- **默认等级**写在 `extra["command_permissions"]` 与/或 `registry.DEFAULT_COMMAND_PERMISSIONS`；运行中可由 WebUI「命令权限」或环境变量覆盖。
- **不要在面向用户的文案里写死权限角色**：`PluginMetadata.usage`、`menu_data.trigger_condition` 中避免「仅群管」「默认群主」「群管理员可…」等静态描述；实际「何人可用」由帮助图根据 `command_permission(s)` 与覆盖配置**动态生成**。
- **`usage` 末行**（有独立命令权限时推荐，参考 `greeting` / `duel`）：
  `所需权限以「牛牛帮助」本插件功能详情为准（可由 WebUI「命令权限」覆盖）。`
- **`menu_data`**：`trigger_condition` 只写触发方式；权限绑定 `command_permission` / `command_permissions`。
- **与 cmd_perm 无关的额外条件**（例如须**处理消息的牛牛账号**为 QQ 群管）：写在 `detail_des` 或 `docs/plugins/<name>/README.md`，不要塞进 `usage` / `trigger_condition`。
- 开发者向 `docs/plugins/*/README.md` 可用表格列出**代码默认等级**（如「群管/群主」），并注明以 WebUI / cmd_perm 为准。

细则与自检清单见 [docs/common/cmd_perm/README.md](docs/common/cmd_perm/README.md)。

### 提交与 PR

- **一个 PR 只解决一类问题**（功能/修复/重构/文档不要混杂）。
- **推荐提交说明格式**（与日常中文习惯一致）：`feat(scope): 简要中文说明`；`fix` / `refactor` / `chore` / `docs` 等同理加 scope 与中文说明。
- 仍可采用英文摘要式前缀（与常见开源习惯兼容），例如：
  - `feat:` 新功能
  - `fix:` 修复
  - `refactor:` 重构（不改变外部行为）
  - `chore:` 构建/工具链/依赖
  - `docs:` 文档
- **自动化 Agent 创建 git commit 前**：先给出**提交信息草案**供维护者确认，**得到确认后再提交**。

### Git 操作边界

- **不要**擅自 `git push`、修改 `git config`，或进行重置/强推等**破坏性**操作，除非维护者在任务中明确要求。
- 需要分支、合并、提交等操作时，以维护者指示为准；敏感操作先确认再执行。

## pre-commit.ci

仓库包含 `.pre-commit-ci.yaml`，用于开启 pre-commit.ci：

- 按较低频率自动更新 hooks 版本（当前为 `quarterly`）
- 在 PR 上自动应用可自动修复的变更（例如格式化、部分 lint autofix）
- 使用中文自动更新提交信息，便于与仓库日常提交风格保持一致
- 与本仓库 pre-commit 约定对齐：基础文件卫生检查覆盖全仓，Ruff 仅作用于 `src/`（避免无关目录被 Python 工具链改写）

启用方式：

1. 在 GitHub 上安装/启用 pre-commit.ci（对该仓库授权）
2. 确保仓库根目录包含：
   - `.pre-commit-config.yaml`
   - `.pre-commit-ci.yaml`
