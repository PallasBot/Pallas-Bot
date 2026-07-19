# AGENTS.md

本文件用于指导人类贡献者与自动化 Agent（例如 Cursor/CI Bot）在本仓库内一致地工作：如何安装依赖、运行检查、提交变更，以及应遵守的约定。

## 项目概览

- **项目名**：Pallas-Bot
- **语言/运行时**：Python **3.12**
- **依赖管理**：`uv`
- **主要代码目录**：`pallas/`（内核）、`packages/`（内置插件）
- **质量门禁（CI）**：Ruff lint/format + 依赖漏洞扫描 + Docker 构建校验（见 `.github/workflows/ci.yml`）

## 本地开发与质量门禁

人类贡献者的完整步骤见 [docs/develop/environment.md](docs/develop/environment.md) 与 [docs/develop/workflow.md](docs/develop/workflow.md)。

Agent 提交前至少执行：

```bash
uv run ruff check pallas/ packages/
uv run ruff format --check pallas/ packages/
```

pre-commit 策略：**全仓**基础文件卫生检查；**Ruff 覆盖 `pallas/`、`packages/`、`local/plugins/`**；`check_plugin_imports.py` 校验 import 规则；`.env` 全局排除。详见 [workflow.md](docs/develop/workflow.md)。

## 文档与排障入口

- **开发指南**：[docs/develop/README.md](docs/develop/README.md)（环境、流程、插件与 WebUI）。
- **插件专项说明**：[docs/plugins/README.md](docs/plugins/README.md)（各子目录 `README.md` 与 `packages/<name>/` 对应）。
- **命令权限（cmd_perm）**：[docs/common/cmd_perm/README.md](docs/common/cmd_perm/README.md)（可配置等级、WebUI 覆盖、帮助菜单「何人可用」）。
- **运行配置存储**：[docs/developer/architecture/config-storage.md](docs/developer/architecture/config-storage.md)（`pallas.toml` + `webui.json`，勿再向根目录 `.env` 写入新项）。
- **`pallas/` 内核分层**：[docs/developer/architecture/overview.md](docs/developer/architecture/overview.md)（3.x 历史对照 → 现行 `pallas/core`）
- **内核插件统一化**：[docs/developer/plugin-development/golden-plugin.md](docs/developer/plugin-development/golden-plugin.md)（core golden 模板、`pb_*` 命名、分期 PR）。
- **热重载分级**：[docs/developer/plugin-development/reload-and-activation.md](docs/developer/plugin-development/reload-and-activation.md)（配置 / 元数据 / 代码；`reload_policy`）。
- **常见问题与部署排障**：[docs/FAQ.md](docs/FAQ.md)。

## 运行配置（Agent 必读）

- **主配置**：复制 [`config/pallas.example.toml`](config/pallas.example.toml) 为 **`config/pallas.toml`**（已 gitignore），填写 `[bootstrap]`（监听、数据库等）。
- **WebUI 落盘**：插件与通用项写入 **`data/pallas_config/webui.json`**；只读快照 **`config/pallas.webui.export.toml`** 由保存自动生成。
- **合并顺序**：`pallas.toml` → 遗留 `.env` / `.env.{ENVIRONMENT}` → `webui.json`（后者覆盖前者；**WebUI 落盘最高**）。
- **读取 API**：`pallas/core/foundation/config/repo_settings.py` 的 `repo_env_raw_value()` / `merged_repo_settings_upper()`；启动前 `apply_repo_settings_to_environ()`。
- **从旧 `.env` 迁移**：`uv run python tools/migrate_env_to_pallas.py`（一次性）；**`.env` 仍可保留**专放 nb/pip 插件项（见 `.env.example`），与 `webui.json` 避免同名键重复。
- **分片可选 Redis**：在 `pallas.toml` 的 `[env]` 配置 `REDIS_URL`；`run_sharded_bot.sh` 自动探测。依赖：`uv sync --extra coord-redis` 或 `uv sync --extra deploy-shard`。
- **可选部署模板**：`deploy/` 目录 + `uv sync --extra deploy-shard`；应用 `uv run python tools/apply_deploy_profile.py shard`（分片）。消息审查 4.0 默认开启，无需模板。
- **Docker Compose 数据库**：仍可用 [`config/compose.env.example`](config/compose.env.example)（仅编排插值，非 Bot 主配置）。

## Agent 工作约定

### 修改范围

- **优先修改 `pallas/`、`packages/` 与 `tests/`**，避免无意义的重排/大范围格式变化。
- **不提交密钥与私密配置**：例如 `config/pallas.toml`、`data/`、`webui.json`、token、私钥、访问凭据等。
- **依赖变更需谨慎**：新增依赖优先走 `pyproject.toml`（`uv` 工作流），并确保 CI 仍能通过。
- **最小必要改动**：只改完成任务所需的代码与文件；避免「顺手」重构无关模块、扩大 diff。
- **全仓格式化/尾随空格/无关换行**：非任务所需不要做；若某次检查或格式化会**波及大量历史文件**，先向维护者说明影响范围再执行。
- **历史问题**：若发现与本次任务无关的遗留问题，在说明中区分「历史遗留」与「本次引入」；不要默认在同一变更里大包大揽修复。

### 代码质量与风格

- **Ruff 是唯一强制的 lint/format 工具**（与 CI/预提交一致）。
- **Ruff 仅 `pallas/`、`packages/`**；`.env` 全局排除。详见 [workflow.md](docs/develop/workflow.md)。
- **与周边代码一致**：命名、类型、抽象层次、导入风格、注释密度与文件内既有写法对齐；优先复用已有函数。
- **新增函数**：非必要**不要**以下划线 `_` 作为前缀。
- **注释**：保持精简；obvious 逻辑不必长段 docstring。

### 日志（NoneBot / loguru）

- 项目常用 **loguru 风格**的 `logger`（如 NoneBot 提供的 logger）。
- 占位符优先使用 **`{}`** 或整条 **f-string**，避免沿用标准库 `logging` 的 `logger.debug("msg %s", x)` 写法，以免消息中仍出现字面量 `%s`。

### 语言与协作文档

- 与维护者/PR 描述可用 **中文**；**代码标识符、配置键名、路径、命令** 保持仓库既有习惯（多为英文键名，勿强行翻译）。
- 修改 **配置、文档、CI/自动化** 时，可补充**简短注释**说明用途即可，不必在注释里长篇解释动机（动机放在 PR/对话里）。

### WebUI 与控制台页面（窄屏）

改动 **Pallas-Bot-WebUI** 或主仓内嵌控制台 HTML/CSS（如 `packages/pb_protocol/web/static/`）时：

- **必须考虑窄屏（≤560px）**：面板标题栏、「添加到侧栏」、表格与批量操作在窄屏下仍须可用、布局不杂乱。
- WebUI 约定见 **Pallas-Bot-WebUI** 仓库根目录 `AGENTS.md`（窄屏自检清单与参考页面）；全局断点与 override 在 WebUI `src/styles/app.css` 的 `@media (max-width: 560px)`。
- 勿只验证桌面宽屏即认为 UI 已完成。

### 插件命令权限与帮助文案（cmd_perm）

接入可配置命令权限的插件时：

- **默认等级**写在 `extra["command_permissions"]` 与/或 `registry.DEFAULT_COMMAND_PERMISSIONS`；运行中可由 WebUI「命令权限」或环境变量覆盖。
- **不要在面向用户的文案里写死权限角色**：`PluginMetadata.usage`、`menu_data.trigger_condition` 中避免「仅群管」「默认群主」「群管理员可…」等静态描述；**勿在 `usage` 末尾重复写权限说明**——帮助图会根据 `command_permission(s)` 与 WebUI 覆盖**自动展示**「何人可用」。
- **`menu_data`**：`trigger_condition` 只写触发方式；权限绑定 `command_permission` / `command_permissions`。
- **文案格式**：`usage` 用 `usage_line` + `join_usage`（≥2 条自动编号）；`description` 一句句号结尾；`brief_des` / `detail_des` 与 `trigger_scene` 见 [cmd_perm · 写法约定](docs/common/cmd_perm/README.md)。
- **与 cmd_perm 无关的额外条件**（例如须**处理消息的牛牛账号**为 QQ 群管）：写在 `detail_des` 或 `docs/plugins/<name>/README.md`，不要塞进 `usage` / `trigger_condition`。
- 开发者向 `docs/plugins/*/README.md` 可用表格列出**代码默认等级**（如「群管/群主」），并注明以 WebUI / cmd_perm 为准。

细则与自检清单见 [docs/common/cmd_perm/README.md](docs/common/cmd_perm/README.md)。

### 内核插件（core）与 golden 模板

`CORE_PLUGIN_NAMES` 见 `src/platform/bot_runtime/plugin_matrix.py`（含 `pb_core`、`pb_stats`、`pb_webui` 等）。维护者向内核插件包名优先 **`pb_*`**；历史名经 `plugin_package_aliases.py` / `plugin_legacy_names.py` 别名兼容（如 `community_stats` → `pb_stats`）。

**标准目录**（参考 `pb_core`、`pb_stats`）：

```text
packages/<name>/
├── __init__.py    # PluginMetadata + matcher/路由注册（薄，目标 ≤120 行）
├── config.py      # Pydantic + install_hot_reload_config（有插件页配置时）
├── handlers.py    # 口令 handler（优先 plugin_sdk）
└── startup.py     # 可选：@driver.on_startup、HTTP 挂载
```

- **口令型**：`plugin_sdk.message_command` + `bind_alias_handlers`；`command_permissions` / `command_limits` / `menu_data` 与命令 ID 一致。
- **维护者向、无群口令**：`help_audience: maintainer`；说明写在 `menu_data` 或 WebUI 通用配置段（如 `pb_stats` → 段 ID `community_stats`）。
- **配置热载**：插件页用 `install_hot_reload_config`；横切项在 `env_sections.py` 注册通用段。
- **元数据热载**：频繁改 help/ingress 声明时设 `extra["reload_policy"]: "metadata"`（见 [hot-reload-tiers.md](docs/developer/plugin-development/reload-and-activation.md)）。
- **分片**：hub-only 逻辑在 `startup.py` 用 `is_sharded_worker()` 守卫；hub 显式名单见 `roles.HUB_PLUGIN_MODULES`。

完整 checklist：[docs/skills/pallas-plugin-development/references/08-golden-plugin-checklist.md](docs/skills/pallas-plugin-development/references/08-golden-plugin-checklist.md)。

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
