# 一、插件基础结构

Pallas 插件运行在 **NoneBot2** 之上，业务代码落在 `packages/` 或站点 `local/plugins/`；横切能力由 `pallas.api.*` 等内核层提供（见 [架构总览](../../../developer/architecture/overview.md)）。骨架权威页：[Golden Plugin](../../../developer/plugin-development/golden-plugin.md)、[getting-started](../../../developer/plugin-development/getting-started.md)。

## 1.1 两种参与方式

| 方式 | 目录 | 适用 |
| --- | --- | --- |
| **贡献主仓** | `packages/<name>/` | 可上游合并的功能 |
| **站点自有** | `local/plugins/<name>/` | 私有定制、避免与主仓 diff 混杂 |

站点插件需在 `config/pallas.toml` 配置 `extra_plugin_dirs`（指向 `local/plugins` 等），**重启后**加载。与主仓同名包时 **local 覆盖**主仓实现。详见 [升级与站点定制](../../../maintainer/deploy/upgrade.md)。

## 1.2 最小目录

```
packages/<name>/   # 或 local/plugins/<name>/
├── __init__.py    # PluginMetadata + Matcher 注册（薄，目标 ≤120 行）
├── config.py      # 配置；WebUI 插件页可调时接热重载
├── handlers.py    # 命令 handler（优先 plugin_sdk）
└── startup.py     # 可选：启动钩子（pb_stats、pb_webui 等）
```

## 1.3 入口与命名

1. `__plugin_meta__` → Matcher → handler（业务不堆在 `__init__.py`）
2. 包名小写+下划线；内核维护者向：`pb_<role>`（如 `pb_core`、`pb_stats`、`pb_webui`）
3. 命令 ID：`my_plugin.action`；改名同步 `plugin_package_aliases.py` / `plugin_legacy_names.py`
4. 新增函数非必要不要 `_` 前缀

## 1.4 core、bundled play 与 extra

| 类型 | 矩阵 | 默认加载 | catalog kind | 示例 |
| --- | --- | --- | --- | --- |
| **core** | `CORE_PLUGIN_NAMES`（`pallas/core/platform/bot_runtime/plugin_matrix.py`） | slim 也加载 | `core` | `repeater`、`pb_stats`、`pb_core`、`llm_chat` |
| **bundled play** | `BUNDLED_PLAY_PLUGIN_NAMES` | 是（随主仓 `packages/`） | `bundled` | `drink`、`greeting`、`roulette`、`take_name` |
| **extra** | `EXTRA_PLUGIN_PACKAGES` | 需 `load_bundled_extra` 或 pip | 视包而定 | `duel`、`pb_protocol` |

在线统计已升格为 core **`pb_stats`**（业务在 `pallas/product/community_stats/`；配置在插件页，落盘兼容 ID 仍可能为 `community_stats`）。

## 1.5 公开 API（允许 import）

| 层 | 路径 | 典型用途 |
| --- | --- | --- |
| api | `pallas.api.commands` | 命令注册、PluginHandlerContext |
| api | `pallas.api.perm` | 命令权限 helper |
| api | `pallas.api.metadata` | 帮助文案、菜单模板常量 |
| api | `pallas.api.limits` | 命令 CD（`cmd_limit:{id}`） |
| api | `pallas.api.config` | `install_hot_reload_config` |
| api | `pallas.api.paths` | `plugin_data_dir`、`resource_dir` |
| api | `pallas.api.storage` | `GroupPluginStorage` |
| api | `pallas.api.safety` | `message_scrub` 入站过滤 |
| product | `pallas.product.*` | 内置专用实现（如 `message_scrub`） |

> **社区 / pip**：仅 `pallas.api.*`（L1）。**内置 `packages/`**：core 插件优先 `pallas.api.*`（perm/commands/limits/storage/config）；可用 `pallas.product.*`（L2）；禁止深层 `pallas.core.*` 私有文件。CI：`tools/check_plugin_imports.py`（`packages/` 禁 `src.` / `dotenv`；`--strict-packages` 禁直连 core perm/commands/limits/storage）。

布局：[repo-layout.md](../../../developer/reference/repo-layout.md)。反例：从 `packages.other_plugin` 直接 import 业务 → 共享能力下沉到 `pallas/`。

## 1.6 最小元数据骨架

完整例见 [Golden Plugin](../../../developer/plugin-development/golden-plugin.md) / [first-plugin](../../../developer/plugin-development/first-plugin.md)。Agent 核对：

- [ ] `command_permissions` / `menu_data` / matcher `permission` 同一 `command_id`
- [ ] `usage` 用 `usage_line` + `join_usage`；无写死权限角色
- [ ] 命令型优先 `group_command` / `message_command` + `bind_alias_handlers`
- [ ] WebUI 可调 → `install_hot_reload_config` + `get_config()`（见 [四](./04-webui-config.md)）

## 1.7 加载与发现

- `packages/`：启动自动发现
- `local/plugins/`：`extra_plugin_dirs` + **重启**
- 额外 pip 包：按 `pyproject.toml` / NoneBot 机制并列加载

## 1.8 下一步

- 选 Matcher → [二、Matcher 决策树](./02-matchers-decision.md)
- 权限与帮助 → [三、cmd_perm](./03-cmd-perm-and-help.md)
