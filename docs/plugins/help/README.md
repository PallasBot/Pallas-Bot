# 牛牛帮助 `help`

查看功能说明，并管理本群常用插件开关。需要查命令、看「何人可用」，或对本群开关某插件时用本插件。

**类型**：本体 core（默认加载）

## 安装

默认加载，无需单独安装。

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛帮助` | 群内 / 私聊 | 插件总览与开关状态 |
| `牛牛帮助 <插件名或序号>` | 群内 / 私聊 | 单个插件功能表 |
| `牛牛帮助 <插件> <功能序号或名称>` | 群内 / 私聊 | 某条功能详情 |
| `牛牛开启` / `牛牛关闭` `<插件名或序号>` | 群内 | 开关单个插件 |
| `牛牛开启全部功能` / `牛牛关闭全部功能` | 群内 | 批量开关本群功能 |

帮助图会根据各插件 `PluginMetadata` 与命令权限动态生成「何人可用」，无需在 usage 里写死角色。

## 普通菜单与超管菜单

帮助**不是**两套静态菜单，而是同一套 metadata，按调用者切换过滤。

| 谁 | 场景 | 行为 |
| --- | --- | --- |
| 任何人 | 群聊，或非超管私聊 | 普通帮助总览（标题「牛牛帮助」） |
| 超管 | **仅私聊** | 超管帮助总览（标题「牛牛帮助（超级用户）」） |

实现：`packages/help/handlers.py` 里 `show_ignored = 超管 and 私聊`，再交给 `get_help_menu_plugins(show_ignored=…)`。

### 过滤层次（由外到内）

1. **内置隐藏**（`BUILTIN_HELP_HIDDEN_PLUGINS`，如 `pb_webui`、`pb_stats`）：永远不进帮助总览。
2. **插件级** `extra.help_audience`：值为 `superuser` 或历史别名 `maintainer` 时，整插件不进**普通**总览；超管私聊可见（仍受内置隐藏约束）。缺省视为面向用户。
3. **配置忽略名单** `ignored_plugins`：普通模式再滤一层；超管私聊模式跳过。
4. **条目级** `menu_data[].help_audience`：普通视图的插件详情里隐藏标了 `superuser` / `maintainer` 的条目；**超管私聊**详情与命令直达会展示这些条目。缺省可见。

```text
牛牛帮助
  ├─ 普通视图：用户向插件 + 用户向 menu 条目
  └─ 超管私聊：+ 插件级 help_audience 受限插件、配置里 ignored 的插件
       + 混合插件里条目级 help_audience 受限命令（如 pb_core 的「牛牛更新」）
       （内置 hidden 仍不出现）
```

### 与命令权限的区别

| 字段 | 管什么 |
| --- | --- |
| `command_permissions` / cmd_perm | **谁能执行**命令；帮助图「何人可用」读这个 |
| `help_audience` | **谁能在帮助里看见**插件或条目 |

可执行 ≠ 一定出现在普通帮助。例如某命令默认号主可用，但仍可把整插件标成超管向，则普通总览不出现。

混合插件示例（`pb_core`）：插件级不标超管 → 进普通总览；仅「运行状态」（触发 `#pallas`）为用户向条目，重启 / 更新等条目标 `help_audience: superuser`。面向用户的 `usage` 只列普通可见命令。

声明与过滤实现：`pallas.core.perm.help_menu`（经 `pallas.api.perm` 导出）。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `help.help` | 所有人 |
| `help.plugin_enable` | 群管或号主 |
| `help.plugin_disable` | 群管或号主 |
| `help.plugin_enable_all` | 群管或号主 |
| `help.plugin_disable_all` | 群管或号主 |

实际生效等级以控制台「命令权限」为准。

## 配置

控制台对应插件页。样式、忽略名单等见 [`packages/help/config.py`](../../../packages/help/config.py)。视觉说明见 [VISUAL.md](./VISUAL.md)。

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 帮助图生成失败 | 检查样式配置、素材路径和日志 |
| 开关看起来没生效 | 确认操作的是当前群，且目标插件没有额外独立开关 |
| 超管在群里看不到维护者向插件 | 超管扩展总览仅私聊生效；请私聊该牛发「牛牛帮助」 |
| 插件在普通帮助里消失 | 查 `extra.help_audience`、help 配置 `ignored_plugins`、是否在内置 hidden 名单 |

## 源码

[`packages/help/`](../../../packages/help/)

- `__init__.py`：元数据、命令权限与帮助菜单
- `handlers.py`：普通 / 超管私聊双视图入口
- `plugin_manager.py`：总览插件集合与过滤
- `visibility.py`：内置隐藏与忽略名单
- `commands.py`：帮助查询与群内开关
- `config.py`：帮助图样式等

## 相关链接

- [命令权限](../../common/cmd_perm/README.md)（含 `help_audience` 与鉴权的分工）
- [元数据](../../developer/plugin-development/metadata.md)
- [文档结构模板](../TEMPLATE.md)
