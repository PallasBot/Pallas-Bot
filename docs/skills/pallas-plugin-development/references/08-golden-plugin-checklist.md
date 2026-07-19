# 八、完整插件 checklist（提交前）

新建或较大改动插件时，逐项勾选：

## Core 插件（`CORE_PLUGIN_NAMES`）

- [ ] `__init__.py` 薄（目标 ≤120 行）；`startup.py` 承载启动/HTTP 注册
- [ ] 口令型：`plugin_sdk` + `handlers.py`；`command_permissions` / `command_limits` / `menu_data` 齐全
- [ ] 维护者向：`help_audience: maintainer`；无群口令时用 `menu_data` 指向 WebUI 路径
- [ ] 配置：插件页 `install_hot_reload_config`；或通用段 + `features/`（参考 `pb_stats`）
- [ ] 改名保留别名：`plugin_package_aliases.py`、`plugin_legacy_names.py`
- [ ] 分片 hub-only：`is_sharded_worker()` 守卫；`roles.py` 名单与矩阵单测

参照：`pb_core`（口令）、`pb_stats`（维护者向 + 通用段）。

## 结构与代码

- [ ] `__init__.py` 轻量；业务已拆到语义化模块
- [ ] `config.py` 存在；WebUI 可调项已接 `install_hot_reload_config`（或通用配置段 + features 层）
- [ ] 改 help/ingress 声明且不想重启：已设 `reload_policy: metadata`
- [ ] 结构化状态：`extra["plugin_storage"]` + `GroupPluginStorage`（或 deploy 级声明）；大文件才用 `plugin_data_dir` / `resource_dir`
- [ ] 导入来自 `pallas.api.*`（社区插件）或 `pallas.api.*` + `pallas.product.*`（内置插件）
- [ ] `uv run ruff check packages/`（或 `local/plugins/`）与 `format --check` 通过

## Matcher 与权限

- [ ] 口令型用 `on_command`；被动型 `on_message` 有合理 priority/block/rule
- [ ] 每个鉴权命令有 `command_permissions` + matcher permission
- [ ] `menu_data` 与命令 ID 一致
- [ ] `usage` / `trigger_condition` 无写死权限文案

## 横切能力

- [ ] 读用户原文学习/生成类已评估 message_scrub
- [ ] 高频路径无同步阻塞；日志用 `{}` / f-string

## 测试与文档

- [ ] `tests/plugins/<name>/` 有最小测试
- [ ] `docs/plugins/<name>/README.md` + 索引更新

## 站点插件（local）

- [ ] 放在 `local/plugins/<name>/`
- [ ] `pallas.toml` 已配 `extra_plugin_dirs`
- [ ] 与主仓同名时确认覆盖意图

## 可选增强

- [ ] 需 CD 时已用 `pallas.api.limits`（或 `GroupConfig` / `BotConfig`），key 与 `command_id` 一致
- [ ] 多牛 / 分片部署已读 [分片运行时](../../developer/architecture/shard-runtime.md)、[分片部署](../../maintainer/deploy/sharded.md)
