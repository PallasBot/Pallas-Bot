# 命令权限（cmd_perm）

本页说明部分命令的「谁可用」如何声明与覆盖：代码写默认等级，WebUI 可覆盖；**牛牛帮助**自动展示当前生效的「何人可用」。

接群命令时先在 [写第一个插件](/developer/plugin-development/first-plugin) 对齐命令 ID，再回到本页补权限与帮助文案约定。

**用语**：面向用户（帮助、`usage`、控制台）统一称「**命令**」，不要写「口令」。控制台登录称「密钥」；社区统计 / 共享语料访问凭证可保留「口令」。

实现：`pallas.core.perm`；**插件侧只从 `pallas.api.perm` import**。

## 等级

| 配置值 | 含义 |
| --- | --- |
| `everyone` | 不额外限制（仍受私聊/群等事件约束） |
| `bot_moderator` | 号主（`admins` 等） |
| `group_moderator` | 群管/群主；私聊时等价号主侧判定 |
| `staff` | 群管/群主 **或** 号主 |
| `superuser` | 仅超管 |

## 配置（运维）

| 项 | 说明 |
| --- | --- |
| WebUI | **通用配置 → 命令权限** |
| 落盘 | `data/pallas_config/webui.json` 键 `PALLAS_COMMAND_PERMISSION_OVERRIDES` |
| 优先级 | `pallas.toml` / env → 可被 WebUI 覆盖；**WebUI 最高** |
| 生效 | 改覆盖后清缓存，**通常无需重启**；改 Python 默认需重启或 reload |

命令 ID：`{插件}.{动作}`（如 `help.help`）。同一 ID 须在鉴权、registry、metadata、帮助里一致。运维短页：[命令权限](/maintainer/operate/command-permissions)。

## 插件接入

### Matcher

```python
from pallas.api.perm import (
    group_message_permission_for_command,
    permission_for_command,
    private_message_permission_for_command,
)

# 通用
permission_for_command("my_plugin.demo")

# 限定群 / 私聊时用合并 helper，勿手写 Permission & ...
group_message_permission_for_command("my_plugin.demo")
private_message_permission_for_command("my_plugin.demo")
```

命令注册优先 `pallas.api.commands`（`group_command` / `bind_alias_handlers`），内部会接权限。

### 默认等级

```python
from pallas.api.perm import command_perm_list, command_perm_row

extra={
    "command_permissions": command_perm_list(
        command_perm_row("my_plugin.demo", "示例命令", "everyone"),
    ),
}
```

也可写入 registry 底表兜底；metadata 同 ID 的 `default` 覆盖底表。

### 帮助 `menu_data`

| 字段 | 要点 |
| --- | --- |
| `trigger_condition` | 命令原文；**不写**权限角色 |
| `command_permission(s)` | 与鉴权 ID 一致 |
| `usage` | `usage_line` + `join_usage`；**勿**写权限脚注 |
| `help_audience` | 帮助**可见性**（谁能在帮助里看见），与「谁能执行」分开 |

```python
from pallas.api.metadata import SCENE_GROUP, join_usage, usage_line
```

业务前提（如须本 Bot 为 QQ 群管）写 `detail_des` 或插件 README，不进 `usage`。

#### 帮助可见性 `help_audience`

与 cmd_perm 等级正交：改「何人可用」不会自动改帮助里显不显示。

| 写在哪 | 值 | 普通「牛牛帮助」 |
| --- | --- | --- |
| 插件 `extra.help_audience` | `superuser` / `maintainer` | 整插件不出现 |
| `menu_data[].help_audience` | 同上 | 该条目不出现在**普通**详情；超管私聊详情可见 |
| 缺省 / `user` | — | 可见 |

超管**私聊**发「牛牛帮助」可看到插件级受限与配置忽略名单中的插件（内置 hidden 除外）。机制与排障见 [牛牛帮助 · 普通菜单与超管菜单](/plugins/help/README.md#普通菜单与超管菜单)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 帮助与实鉴权不一致 | 核对 `menu_data` 与 `permission_for_command` 是否同一 ID |
| WebUI 矩阵缺命令 | 补 `command_permissions` |
| 覆盖不生效 | 确认已保存 `webui.json`；调用侧是否清缓存 |

## 实现索引

| 模块 | 职责 |
| --- | --- |
| `pallas.core.perm.check` | `permission_for_command`、`satisfies_command_permission` |
| `pallas.core.perm.config` | 覆盖读取、`clear_cmd_perm_cache` |
| `pallas.core.perm.registry` | 合法等级、默认表 |
| `pallas.core.perm.schema` | 合并 metadata、WebUI 矩阵 |
| `pallas.core.perm.menu_display` | 帮助文案 |
| `pallas.core.perm.help_menu` | `help_audience` 过滤、`iter_plugin_detail_menu` |
| `pallas.core.perm.metadata_text` | `usage_line` / `join_usage` |

## 上线自检

- [ ] 独立鉴权入口共用同一命令 ID
- [ ] `command_permissions` 含可读 `label`
- [ ] `menu_data` 已绑 `command_permission`，`trigger_condition` 无静态角色
- [ ] `usage` 未写死权限角色
- [ ] 维护者向整插件或单条目已按需设 `help_audience`（与默认执行等级分开考虑）

## 后续阅读

- [命令冷却](/common/command_limits)
- [牛牛帮助（含双菜单）](/plugins/help/README.md#普通菜单与超管菜单)
- [写第一个插件](/developer/plugin-development/first-plugin)
- [元数据](/developer/plugin-development/metadata)
