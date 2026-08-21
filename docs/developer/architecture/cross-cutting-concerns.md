# 平台横切能力全景

本页描述一层插件在收到消息后，平台按什么顺序、用什么机制，为其附加权限、冷却、存储与重载等「横切」能力。写插件前先读 [Golden Plugin](/developer/plugin-development/golden-plugin)，需要排障时看运维侧 [命令权限](/maintainer/operate/command-permissions) 与 [插件治理](/maintainer/operate/plugin-governance)。

一句话模型：**声明在 metadata（`extra` 或 `PluginMetadata`），合并落在 `pallas.core.*.schema`，生效路径走 ACL / permission / cooldown / storage / reload 五条独立通道**——每条通道的「默认」都可被 WebUI 覆盖，分片下多条进程共享同一覆盖结果。

## 判定顺序（一次消息经历什么）

```text
事件进入
  └─ ACL（pallas.core.perm.acl）    最外层：全局 / 群 / 用户 / 插件级 deny 优先
  └─ 命令明文识别 + alias           谁能触发 → 命令 ID 定稿
  └─ cmd_perm 检查（check.py）      ID 的生效等级 + 场景
  └─ cooldown（limits）             ID 冷却是否放行
  └─ 命令 handler / menu           若要写状态 → storage；config 变化 → reload
```

## 能力全景

| 能力 | 声明位置 | 合并与读取 | WebUI 覆盖 | 生效时间 | 分片 |
| --- | --- | --- | --- | --- | --- |
| 命令权限 | `extra["command_permissions"]` / 插件级 <br> `command_perm_list`、`command_perm_row` | `perm/schema.py` `merged_default_levels()`；<br>读取 `resolved_level()` | `PALLAS_COMMAND_PERMISSION_OVERRIDES`<br>（通用配置 → 命令权限） | 改动即生效 | 共享同一覆盖结果 |
| 命令冷却 | `extra["command_limits"]` <br> `command_limit_list`、`command_limit_row` | `limits/schema.py` `merged_default_command_limits()`；<br>读取 `effective_command_limit_for()` | `PALLAS_COMMAND_LIMIT_OVERRIDES`<br>（通用配置 → 命令冷却） | 改动即生效 | 同上 |
| 插件数据 | `extra["plugin_storage"]` <br> `plugin_storage_list`、`plugin_storage_row` | `storage/schema.py` `merged_storage_registry()`；<br>读取 `get_plugin_storage()` | 控制台「插件数据」（只读视角） | 声明改动需重启加载 | 内存值按进程；持久值共享 DB |
| 热重载配置 | `install_hot_reload_config`（插件 `config.py`） | `foundation.config.repo_settings` → `webui.json`；<br>读取 `get_*_config()` | 控制台配置页保存 | 同进程立即；worker 比对磁盘 revision | 见 [配置存储](config-storage.md) |

> `everyone` / `bot_moderator` / `group_moderator` / `staff` / `superuser` 等级含义与「何人可用」帮助文案见 [命令权限（cmd_perm）](/common/cmd_perm)。

## 1. ACL（先于 cmd_perm）

ACL 是全局访问控制层，在 cmd_perm 之前最外层判定。三层规则：

| 优先级 | 规则来源 | 例子 |
| --- | --- | --- |
| `admin_bypass`（始终命中） | `admin_members` 表（启动时从 `BotConfig.admins` 迁移） | 号主总能执行 |
| rule（按 priority 最大值） | 治理页 / ACL webhook 写入；同 priority 时 `deny` 胜出 | 黑名单用户、`plugin.<pkg>` 禁用、`cmd.<id>` 受限、`group:<gid>` 处理群 |
| fallback | 未匹配任何规则默认 `allow` | — |

- 插件被「禁用」时治理页写 `plugin.<package>` deny 规则（priority 1500），即 `sync_plugin_blocked_user_ids`。
- 缓存分级 TTL：decision 60s（上限 5 万条）、rules 180s（空缓存 600s）、admin_ids 180s；webhook/治理页写入后调 `invalidate_acl_rules_cache()`。
- 启动迁移：`run_acl_startup_migrations()` 幂等执行（`migrate_bot_admins_to_admin_members_once`、`derive_acl_from_legacy`），hub/worker 各跑一次。

配置与实现：[ACL 与治理](/maintainer/operate/plugin-governance)。

## 2. 命令权限（cmd_perm）

插件侧**只从 `pallas.api.perm` import**，不要直接 `pallas.core.perm`。

| 环节 | API | 说明 |
| --- | --- | --- |
| 声明 | `command_perm_row(id, label, default)` → `command_perm_list(...)` | 放进 `extra["command_permissions"]` |
| 合并 | `perm/schema.py`：平台 `DEFAULT_COMMAND_PERMISSIONS` ∪ 已加载插件 metadata（未加载插件用磁盘 stub 补全） | 覆盖优先于默认 |
| 判定 | `permission_for_command` / `group_message_permission_for_command` / `private_message_permission_for_command` → `satisfies_command_permission` | ACL 优先；no-ACL 回退 legacy `resolved_level` |
| WebUI | `build_command_perm_ui` 生成矩阵；保存后写 `PALLAS_COMMAND_PERMISSION_OVERRIDES` 并清缓存 | 通常无需重启 |
| 帮助 | `menu_display.py` 生成「何人可用」，`help_menu.py` 按 `help_audience` 过滤自定义菜单 | 与 cmd_perm 正交 |

命令 ID 唯一约束：`{插件}.{动作}`（如 `help.help`）。同一 ID 在鉴权、registry、metadata、帮助中必须一致。`tool` 命名的工具命令（如 `draw.draw`）在统一消息运行时挂钩时为 `bot` 场景，菜单等展示仍按默认展示（见 [消息运行时](message-runtime.md)）。

## 3. 命令冷却（limits）

- 声明：`command_limit_row(id, cd_sec)` → `extra["command_limits"]`；`cd_sec=0` 表示关闭冷却。
- 合并：`limits/schema.py` `merged_default_command_limits()`（同 perm，走插件 metadata + 磁盘 stub）。
- 生效：`is_command_cooldown_ready` / `refresh_command_cooldown`，按 `GroupConfig`（群）与 `BotConfig`（私聊）分别落盘。
- 覆盖：`PALLAS_COMMAND_LIMIT_OVERRIDES`（通用配置 → 命令冷却）。
- 帮助：`limits/menu_display.py` 为菜单补齐「冷却 X 秒 / 无冷却」。

社区插件何时用冷却：[命令冷却](/common/command_limits)。

## 4. 插件数据（storage）

| 维度 | 说明 |
| --- | --- |
| 声明 | `plugin_storage_row(key, scope, label, ephemeral)` → `extra["plugin_storage"]`；scope = `group` / `user` / `bot` / `deploy` |
| 写入 | `get_plugin_storage` / `set_plugin_storage` / `delete_plugin_storage(plugin_name, key, scope_id, scope)`（先 resolve 声明，scope 不符抛 `PluginStorageKeyError`） |
| 便捷类 | `GroupPluginStorage(plugin_name, group_id)` |
| 持久化 | group/user/bot 挂 `GroupConfig` / `UserConfig` / `BotConfig` 的 `plugin_storage`；deploy 走 `DeployPluginStorage`（flock + tmp/rename 原子写 + audit jsonl）→ `data/<plugin>/plugin_storage.json` |
| ephemeral | 只在内存 `_ephemeral_values`，进程重启即清 |
| 清缓存 | 插件重载后 `register_plugin_storage_startup_hook` 会触发 registry 重建；`merged_storage_registry` 兼容插件加载名 / 短 id / `pallas_plugin_` 前缀等多路别名 |

原则：**声明了才能写**；不要在 `pallas.toml` / `webui.json` 里替插件保存运行态小状态；大文件走 `plugin_data_dir` / `resource_dir`。WebUI「插件数据」页展示由 `build_plugin_storage_ui` 提供。

## 5. 热重载（reload）

- `extra["reload_policy"]`：`config_only`（默认）/ `metadata` / `full`。参见 [重载与激活](/developer/plugin-development/reload-and-activation)。
- `metadata`：控制台保存配置后重建 `plugin_command_plaintext`、`local_federate_metadata`、`plugin_storage_registry`、`perm`、help 五类索引（`reload_plugin_metadata_index`）——不重载代码。
- `full`：额外尝试 `importlib.reload`；失败则回落 metadata-only。**matcher 热卸载仍受限**，代码级变更保险做法是重启。
- 配置热载见 [配置存储](config-storage.md) 的「热载与分片」。

## 禁止

1. 插件直接从 `pallas.core.*` deep import 平台横切能力（用 `pallas.api.*`；内置插件可加 `pallas.product.*`）。
2. 擅自把平台横切项塞进插件私有 `webui.json` 或 `pallas.toml` 段——横切项一律走对应通用段 + `PALLAS_COMMAND_*_OVERRIDES`。
3. 在 `usage` / `trigger_condition` 写死权限角色（帮助图会自动展示「何人可用」）。
4. 声明了 `plugin_storage` 但 `delete`/改 scope 时忘记清 registry —— 改声明需重启加载。

## 后续阅读

- [命令权限（cmd_perm）](/common/cmd_perm) · [命令冷却](/common/command_limits) · [配置存储](config-storage.md)
- [插件治理与 ACL](/maintainer/operate/plugin-governance) · [超管命令权限运维](/maintainer/operate/command-permissions)
- [Golden Plugin](/developer/plugin-development/golden-plugin) · [重载与激活](/developer/plugin-development/reload-and-activation)