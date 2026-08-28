# AGENTS.md

本文件用于指导人类贡献者与自动化 Agent（例如 Cursor/CI Bot）在本仓库内一致地工作：如何安装依赖、运行检查、提交变更，以及应遵守的约定。

## 项目概览

- **项目名**：Pallas-Bot
- **语言/运行时**：Python **3.12**
- **依赖管理**：`uv`
- **主要代码目录**：`pallas/`（内核）、`packages/`（内置插件）
- **质量门禁（CI）**：Ruff lint/format + 依赖漏洞扫描 + Docker 构建校验（见 `.github/workflows/ci.yml`）

## 本地开发与质量门禁

人类贡献者的完整步骤见 [docs/developer/environment.md](docs/developer/environment.md) 与 [docs/developer/workflow.md](docs/developer/workflow.md)。

Agent 提交前至少执行：

```bash
uv run ruff check pallas/ packages/
uv run ruff format --check pallas/ packages/
```

## 文档与排障入口

- **开发指南**：[docs/developer/index.md](docs/developer/index.md)（环境、流程、插件与 WebUI）。
- **OpenAPI 契约**：[docs/developer/webui.md](docs/developer/webui.md#openapi-契约)（导出 openspec、WebUI 类型、drift / CI）。
- **插件专项说明**：[docs/plugins/README.md](docs/plugins/README.md)（各子目录 `README.md` 与 `packages/<name>/` 对应）。
- **命令权限（cmd_perm）**：[docs/common/cmd_perm/README.md](docs/common/cmd_perm/README.md)（可配置等级、WebUI 覆盖、帮助菜单「何人可用」）。
- **运行配置存储**：[docs/developer/architecture/config-storage.md](docs/developer/architecture/config-storage.md)（`pallas.toml` + `webui.json`，勿再向根目录 `.env` 写入新项）。
- **`pallas/` 内核分层**：[docs/developer/architecture/overview.md](docs/developer/architecture/overview.md)（3.x 历史对照 → 现行 `pallas/core`）
- **内核插件统一化**：[docs/developer/plugin-development/golden-plugin.md](docs/developer/plugin-development/golden-plugin.md)（core golden 模板、`pb_*` 命名、分期 PR）。
- **热重载分级**：[docs/developer/plugin-development/reload-and-activation.md](docs/developer/plugin-development/reload-and-activation.md)（配置 / 元数据 / 代码；`reload_policy`）。
- **常见问题与部署排障**：[docs/FAQ.md](docs/FAQ.md)。
- **Agent 协作**：[Issue 跟踪](docs/agents/issue-tracker.md)、[Triage 标签](docs/agents/triage-labels.md)、[仓库信息布局](docs/agents/domain.md)。

## 运行配置（Agent 必读）

- **主配置**：复制 [`config/pallas.example.toml`](config/pallas.example.toml) 为 **`config/pallas.toml`**（已 gitignore），填写 `[bootstrap]`（监听、数据库等）。
- **WebUI 落盘**：插件与通用项写入 **`data/pallas_config/webui.json`**；只读快照 **`config/pallas.webui.export.toml`** 由保存自动生成。
- **合并顺序**：`pallas.toml` → 遗留 `.env` / `.env.{ENVIRONMENT}` → `webui.json`（后者覆盖前者；**WebUI 落盘最高**）。
- **读取 API**：`pallas/core/foundation/config/repo_settings.py` 的 `repo_env_raw_value()` / `merged_repo_settings_upper()`（插件经 `pallas.api.config`）；启动前 `apply_repo_settings_to_environ()`。`dotenv` 为弃用兼容层，勿新增依赖。
- **从旧 `.env` 迁移**：`uv run python tools/migrate_env_to_pallas.py`（一次性）；**`.env` 仍可保留**专放 nb/pip 插件项（见 `.env.example`），与 `webui.json` 避免同名键重复。
- **分片可选 Redis**：在 `pallas.toml` 的 `[env]` 配置 `REDIS_URL`；`run_sharded_bot.sh` 自动探测。`redis` 客户端已在主依赖（多机协同 / 分片共用）。
- **可选部署模板**：`deploy/` 目录 + `uv sync --extra deploy-shard`；应用 `uv run python tools/apply_deploy_profile.py shard`（分片）。消息审查 4.0 默认开启，无需模板。
- **Docker Compose 数据库**：仍可用 [`config/compose.env.example`](config/compose.env.example)（仅编排插值，非 Bot 主配置）。

## 运行产物与数据目录（Agent 必读）

日志、持久化、前端资源均落在 **仓库根下 `data/`**（`PROJECT_ROOT / "data"`，见 `pallas/core/foundation/paths/__init__.py` 的 `DATA_ROOT` / `plugin_data_dir()`）。查运行问题时先确认部署形态（unified / 分片 / Docker），再按下面锚点定位。

| 用途 | 路径 |
| --- | --- |
| Bot 业务日志 | `data/bot/nonebot_*.log`（NoneBot loguru，Bot 消息实例持续写入） |
| unified 启动器日志 | `data/pallas_unified/logs/bot_*.log`（后台启动捕获 stdout；主日志以 nonebot 业务日志为准） |
| 业务工作 aux 日志 | `data/pallas_work/logs/work.log`（下载/后台任务） |
| embed 辅进程日志 | `data/pallas_embed/logs/embed.log`（本机 Embedding + Redis 时） |
| 分片日志 / 状态 | `data/pallas_shard/logs/{hub,worker-*}.log`、`registry.json`、`stats/` |
| 配置落盘 | `config/pallas.toml`、`data/pallas_config/webui.json`（WebUI 覆盖最高）、快照 `config/pallas.webui.export.toml` |
| 控制台鉴权 | `data/pallas_console/`：`auth_state.json`（密钥哈希）、`session_secret.bin`、`api_keys.json`（长期 API Key 哈希） |
| WebUI 前端产物 | `data/pb_webui/public-react/`（挂载基址 `/pallas/`） |
| 知识源 | `data/pallas_knowledge/` |
| 表达/口头禅库 | `data/pb_webui/expression_bank/`（历史遗留数据，系统已退役） |
| LLM 反馈/行为 | `data/pb_webui/llm_repeater_feedback/`、`llm_behavior/` |
| 数据库 | PostgreSQL 容器（db `PallasBot`，user `togetsudo`） |

速查命令：`uv run pallas logs`（默认 Bot+embed）、`uv run pallas logs -f`、`uv run pallas status`。排障顺序与关键路径详见 [docs/maintainer/operate/logs.md](docs/maintainer/operate/logs.md) 与 [docs/maintainer/operate/troubleshooting.md](docs/maintainer/operate/troubleshooting.md)。

控制台 API 长期调用：`uv run pallas console token`（签发）、`pallas console tokens` / `pallas console revoke <id>`；请求带 `X-Pallas-Api-Key: pls_...` header（如 `curl -H 'X-Pallas-Api-Key: pls_...' http://<host>:<port>/pallas/api/...`）。

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
- **Ruff 仅 `pallas/`、`packages/`**；`.env` 全局排除。详见 [workflow.md](docs/developer/workflow.md)。
- **与周边代码一致**：命名、类型、抽象层次、导入风格、注释密度与文件内既有写法对齐；优先复用已有函数。
- **新增函数**：非必要**不要**以下划线 `_` 作为前缀。
- **注释**：保持精简；obvious 逻辑不必长段 docstring。

### 日志（NoneBot / loguru）

- 项目常用 **loguru 风格**的 `logger`（如 NoneBot 提供的 logger）。
- 占位符优先使用 **`{}`** 或整条 **f-string**，避免沿用标准库 `logging` 的 `logger.debug("msg %s", x)` 写法，以免消息中仍出现字面量 `%s`。
- **运行态日志正文用英文叙事句**织入关键信息，值用 `[{}]` 内嵌（如 `Bot [{bot_id}] delivered a reply in group [{group_id}]`）；避免中文片段、裸 `key=value` 罗列与键名堆叠，仅键名等需脱敏场景保留「词 [值]」。
- **管理/运维类低频日志**（配置保存、备份、迁移、登录、插件商店、Bot 更新等）用**中文叙事句**织入信息（如 `数据库备份完成，job [{}]、输出到 [{}]`），同样避免裸 `key=value`。
- 每消息/每请求的高频路径（Redis、发送、审查、ACL 等）用 **`log_rate_limited`**（`pallas.core.foundation.logging`）限频，按 key 周期输出一次，避免故障刷屏。

### 语言与协作文档

- 与维护者/PR 描述可用 **中文**；**代码标识符、配置键名、路径、命令** 保持仓库既有习惯（多为英文键名，勿强行翻译）。
- 修改 **配置、文档、CI/自动化** 时，可补充**简短注释**说明用途即可，不必在注释里长篇解释动机（动机放在 PR/对话里）。
- **架构/能力变更必须同步架构文档**：新增或变更模块职责、数据流、记忆/记忆检索、工具、消息链路等结构性质变时，同步更新 `docs/developer/architecture/` 下对应文档（`agent-lifecycle.md`、`llm-output-path.md`、`message-runtime.md`、`config-storage.md` 等），并保持公开文档站（Pallas-Bot-Docs 的 `src/developer/architecture/`）一致。仅配置值/文案微调不在此列。
- **文档站同步机制（勿手动改 Docs 仓正文）**：公开文档站由 CI 自动同步——提交主仓 `docs/**` 或 `tools/scripts/sync_docs_to_web.py` 到 `main`/`docs` 分支即触发 `sync-docs-to-web` 工作流（`.github/workflows/sync-docs-to-web.yml`），自动 commit+push 到 `PallasBot/Pallas-Bot-Docs` 的 `src/`。**无需/不应**手动在 Docs 仓 `src/` 提交正文。例外：新增文档需要出现在公开站**导航/侧栏**时，需在 Docs 仓 `src/.vitepress/config/zh.ts` 手动加条目（sync 脚本只把正文 `.md` 相对链接改写为 GitHub/站内路径，不处理导航）。
- **新增公开文档 checklist**：① 把新页面登记进 `tools/scripts/sync_docs_to_web.py` 的 `FILE_MAP`（否则正文不同步、引用它的页面会死链，Docs 仓 `Deploy to GitHub Pages` 直接失败）；② 若它在公开站导航/侧栏，再在 Docs 仓 `src/.vitepress/config/zh.ts` 加条目；③ 提交主仓后盯 `Sync docs to Pallas-Bot-Docs` 与 Docs 仓 Deploy 两个 CI 至绿。
- **面向用户的用语**（帮助、控制台、插件文案）：

  | 概念 | 用 | 不用 |
  | --- | --- | --- |
  | 插件 / 群触发 | **命令** | 口令 |
  | 控制台登录 | **密钥** | 口令、密码 |
  | 社区统计 / 共享语料访问凭证 | **口令**（可保留） | — |

### WebUI 与控制台页面（窄屏）

改动 **Pallas-Bot-WebUI** 或主仓内嵌控制台 HTML/CSS（如 `packages/pb_protocol/web/static/`）时：

- **必须考虑窄屏（≤560px）**：面板标题栏、「添加到侧栏」、表格与批量操作在窄屏下仍须可用、布局不杂乱。
- WebUI 约定见 **Pallas-Bot-WebUI** 仓库根目录 `AGENTS.md`（窄屏自检清单与参考页面）；全局断点与 override 在 WebUI `src/styles/app.css` 的 `@media (max-width: 560px)`。
- 勿只验证桌面宽屏即认为 UI 已完成。
- **新增暴露到 WebUI 的配置项**：必须同步 `pallas/console/webui/field_labels.py` 的中文名与 `field_help` 说明，否则控制台会显示空键名。约定见 [docs/common/webui/README.md](docs/common/webui/README.md)。

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

`CORE_PLUGIN_NAMES` 与 `BUNDLED_PLAY_PLUGIN_NAMES` 见 `pallas/core/platform/bot_runtime/plugin_matrix.py`。**core**（平台内核，catalog kind `core`）：`pb_core`、`repeater`、`help`、`pb_webui`、`request_handler`、`blacklist`、`llm_chat`、`pb_stats`。**bundled play**（仍默认从 `packages/` 加载，kind `bundled`）：`drink`、`greeting`、`roulette`、`take_name`——不属于 core。官方可选包仍走 `EXTRA_PLUGIN_PACKAGES`。维护者向内核插件包名优先 **`pb_*`**；历史名经 `plugin_package_aliases.py` / `plugin_legacy_names.py` 别名兼容（如 `community_stats` → `pb_stats`）。

**标准目录**（参考 `pb_core`、`pb_stats`）：

```text
packages/<name>/
├── __init__.py    # PluginMetadata + matcher/路由注册（薄，目标 ≤120 行）
├── config.py      # Pydantic + install_hot_reload_config（有插件页配置时）
├── handlers.py    # 命令 handler（优先 plugin_sdk）
└── startup.py     # 可选：@driver.on_startup、HTTP 挂载
```

- **命令型**：`plugin_sdk.message_command` + `bind_alias_handlers`；`command_permissions` / `command_limits` / `menu_data` 与命令 ID 一致。
- **维护者向、无群命令**：`help_audience: maintainer`；说明写在 `menu_data` 或 WebUI 通用配置段（如 `pb_stats` → 段 ID `community_stats`）。
- **配置热载**：插件页用 `install_hot_reload_config`；横切项在 `env_sections.py` 注册通用段。
- **元数据热载**：频繁改 help/ingress 声明时设 `extra["reload_policy"]: "metadata"`（见 [hot-reload-tiers.md](docs/developer/plugin-development/reload-and-activation.md)）。
- **分片**：hub-only 逻辑在 `startup.py` 用 `is_sharded_worker()` 守卫；hub 显式名单见 `roles.HUB_PLUGIN_MODULES`。

完整 checklist：[docs/skills/pallas-plugin-development/references/08-golden-plugin-checklist.md](docs/skills/pallas-plugin-development/references/08-golden-plugin-checklist.md)。

### 提交与 PR

- **一个 PR 只解决一类问题**（功能/修复/重构/文档不要混杂）。
- **推荐提交说明格式**（与日常中文习惯一致）：`feat(scope): 简要中文说明`；`fix` / `refactor` / `chore` / `docs` 等同理加 scope 与中文说明。
- **标题行**：一条提交只做一件事，`type(scope): 中文短句`，避免「修复/新增」等冗余动词开头与主题堆叠；太长时把细节下沉到 body。
- **正文（body，可选）**：与标题空一行；用现在时/祈使句解释**为什么**而非复述 diff；要点可用 `-` 列表；每行 ≤72 字符、段间空行。注意 `git commit` 默认 `cleanup=strip` 会剥掉列表缩进，需保留时用 `--cleanup=verbatim` 或设 `commit.cleanup verbatim`。
- **分支命名**：`feat/xxx`、`fix/xxx`、`refactor/xxx`，scope 用一件具体事；从 dev 拉出，单线开发。侧枝之间**可以互相 merge**（保留早期「主题分支先交叉再合主线」的复杂度感），但每个侧枝最终须能干净合回 dev 主线。
- **merge 标题：统一用 git 自动生成，不手写**。走 PR 则保留 GitHub 自动标题 `Merge pull request #N from ...`；本地直合则保留 `git merge` 自动标题 `Merge branch '...' into ...`。不再使用 `merge: 中文说明` / `merge(scope):` 前缀。
- **merge 结构**：永远真实 merge（`--no-ff`），保留**双父**（第一父=被并入主线，第二父=被合并分支 tip），不得拍扁成单亲 flat merge 导致历史失真；绝不对主线主干 squash。
- **区分「有意义交叉」与「噪声同步」**：允许主题侧枝之间先合并再合主线；但「同名分支/同主干追赶性互并」（`master into master`、`catcat into catcat`）属纯噪声，用 `--rebase` 或 squash 消掉，不算为历史做贡献。
- 仍可采用英文摘要式前缀（与常见开源习惯兼容），例如：
  - `feat:` 新功能
  - `fix:` 修复
  - `refactor:` 重构（不改变外部行为）
  - `chore:` 构建/工具链/依赖
  - `docs:` 文档
- **自动化 Agent 创建 git commit 前**：先给出**提交信息草案**供维护者确认，**得到确认后再提交**。
- **普通 dev→main PR 的 CHANGELOG**：WebUI 与 Bot 发版解耦、Bot 降频后，`dev`→`main` 多为不含 `chore(release)` 的功能 PR。此类 PR 应随批写好 `## [Unreleased]`（只写 `### Added` / `### Fixed` / `### Changed` 明细，不写更新公告、不改版本号），素材随批落到 `main`，供真正发版时整理公告。完整约定见 `docs/skills/pallas-release/SKILL.md` 的「普通 dev→main PR 的 CHANGELOG 约定」。

### Git 操作边界

- **不要**擅自 `git push`、修改 `git config`，或进行重置/强推等**破坏性**操作，除非维护者在任务中明确要求。
- 需要分支、合并、提交等操作时，以维护者指示为准；敏感操作先确认再执行。

## pre-commit hooks

本地安装：`uvx pre-commit install`（或系统/venv 中的 `pre-commit install`）。

- 基础文件卫生检查覆盖全仓；Ruff 覆盖 `pallas/`、`packages/`、`local/plugins/`；`check_plugin_imports.py` 校验 import 规则；`.env` 全局排除。详见 [workflow.md](docs/developer/workflow.md)。
- 每次 commit 会跑 **`sync-console-openapi`**（写出 `openspec/pallas-console-v1.json`；同级有 WebUI 则 gen 类型；有改动需重新 stage）。手动同步见下。
- 控制台 OpenAPI（改 API / 路由后）：`uv run python tools/sync_console_openapi.py` → `openspec/pallas-console-v1.json`；在线 `/pallas/api/openapi.json`；契约细则见 [webui.md · OpenAPI](docs/developer/webui.md#openapi-契约)。合并顺序：先合 Bot（含 openspec）→ 再合 WebUI 类型。

**hooks 版本手动更新**（不启 pre-commit.ci 自动升级；默认会 weekly，且需 org 装 App）：

```bash
uvx pre-commit autoupdate
# 建议将 ruff-pre-commit 的 rev 与 `uv run ruff --version` / uv.lock 对齐后再提交
uv run ruff check pallas/ packages/
uv run ruff format --check pallas/ packages/
```
