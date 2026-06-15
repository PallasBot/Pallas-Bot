# 八、完整插件 checklist（提交前）

新建或较大改动插件时，逐项勾选：

## 结构与代码

- [ ] `__init__.py` 轻量；业务已拆到语义化模块
- [ ] `config.py` 存在；WebUI 可调项已接 `install_hot_reload_config`
- [ ] 路径用 `plugin_data_dir` / `resource_dir`
- [ ] 导入来自 `src.features` / `src.foundation` / `src.console` 公开 API
- [ ] `uv run ruff check src/` 与 `format --check` 通过

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

- [ ] 需 CD 时已用 `src.features.command_limits`（或 `GroupConfig` / `BotConfig`），key 与 `command_id` 一致
- [ ] 多牛 / 分片部署已读 [central-ingress-dispatch](../../architecture/central-ingress-dispatch.md)、[bot_process_sharding](../../architecture/bot_process_sharding.md)
