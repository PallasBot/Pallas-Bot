# 命令权限（cmd_perm）

部分口令的「谁可用」可在运行中配置：代码声明默认等级，WebUI 可覆盖；**牛牛帮助**自动展示当前生效的「何人可用」。

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

口令注册优先 `pallas.api.commands`（`group_command` / `bind_alias_handlers`），内部会接权限。

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
| `trigger_condition` | 口令原文；**不写**权限角色 |
| `command_permission(s)` | 与鉴权 ID 一致 |
| `usage` | `usage_line` + `join_usage`；**勿**写权限脚注 |

```python
from pallas.api.metadata import SCENE_GROUP, join_usage, usage_line
```

业务前提（如须本 Bot 为 QQ 群管）写 `detail_des` 或插件 README，不进 `usage`。

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
| `pallas.core.perm.metadata_text` | `usage_line` / `join_usage` |

## 上线自检

- [ ] 独立鉴权入口共用同一命令 ID
- [ ] `command_permissions` 含可读 `label`
- [ ] `menu_data` 已绑 `command_permission`，`trigger_condition` 无静态角色
- [ ] `usage` 未写死权限角色

## 相关

- [命令冷却](/common/command_limits)
- [首个插件](/developer/plugin-development/first-plugin)
- [元数据](/developer/plugin-development/metadata)
