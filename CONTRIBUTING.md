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

- [开发指南总览](docs/develop/README.md)
- [本地开发环境](docs/develop/environment.md)
- [贡献与提交流程](docs/develop/workflow.md)
- [项目结构约定](docs/developer/reference/repo-layout.md)
- [Golden Plugin / 插件目录约定](docs/developer/plugin-development/golden-plugin.md)
- [命令权限接入说明](docs/common/cmd_perm/README.md)
- [Agent 协作约定](AGENTS.md)

### 本地开发环境

```bash
uv sync --dev
```

首次运行前复制并编辑运行配置（**不要**再依赖根目录 `.env` 作为唯一配置源）：

```bash
cp config/pallas.example.toml config/pallas.toml
# 填写 [bootstrap] 与数据库；其余可在启动后于 WebUI「插件 / 通用配置」中保存到 data/pallas_config/webui.json
```

说明见 [运行配置存储](docs/developer/architecture/config-storage.md)。从旧 `.env` 迁移：`uv run python tools/migrate_env_to_pallas.py`。

分片部署且与 Pallas-Bot-AI 共用 Redis 时，在 `pallas.toml` 的 `[env]` 中设置 `REDIS_URL`，并执行 `uv sync --extra coord-redis`；`./scripts/run_sharded_bot.sh start` 会自动探测。

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

### 插件命令权限（PR 自检）

若 PR 新增或修改可走 cmd_perm 的命令入口，请确认：

- [ ] Matcher / 手动鉴权与 `extra["command_permissions"]`（或 `DEFAULT_COMMAND_PERMISSIONS`）使用**同一命令 ID**
- [ ] `usage`、`menu_data.trigger_condition` **未写死**「群管/群主/仅管理员」等静态权限文案
- [ ] 需要展示的权限已配置 `command_permission` / `command_permissions`，帮助图「何人可用」能反映当前生效等级

详见 [cmd_perm 接入说明](docs/common/cmd_perm/README.md) 与 [AGENTS.md](AGENTS.md) 中「插件命令权限与帮助文案」。

## 沟通方式

如果对贡献流程有疑问，可在 Issue 留言或加入 QQ 开发者群交流。

- QQ 开发者群：`716692626`
