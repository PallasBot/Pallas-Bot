# 命令冷却（command_limits）

在 cmd_perm 鉴权通过后，对高频命令做群级 / 私聊级冷却。

实现：`pallas.core.limits`；**插件侧只从 `pallas.api.limits` import**。

## metadata 声明

```python
from pallas.api.limits import command_limit_list, command_limit_row
from pallas.api.perm import command_perm_list, command_perm_row

extra={
    "command_permissions": command_perm_list(
        command_perm_row("my_plugin.demo", "示例命令", "everyone"),
    ),
    "command_limits": command_limit_list(
        command_limit_row("my_plugin.demo", 10),  # cd_sec
    ),
}
```

| 字段 | 说明 |
| --- | --- |
| `id` | 命令 ID，与 permissions / matcher 一致 |
| `cd_sec` | 冷却秒数（`command_limit_row` 第二参） |
| `scope` | `group` / `private` / `auto`（默认 `auto`） |

声明供 WebUI / 帮助展示；handler 内仍建议显式调用 helper。

## handler

```python
from pallas.api.limits import is_command_cooldown_ready, refresh_command_cooldown

CD_SEC = 10

async def handle_demo(event):
    if not await is_command_cooldown_ready(event, "my_plugin.demo", CD_SEC):
        return
    ...
    await refresh_command_cooldown(event, "my_plugin.demo", CD_SEC)
```

## 与权限的区别

| | 权限 | 冷却 |
| --- | --- | --- |
| 问 | 谁能用 | 多久能再用 |
| 文档 | [cmd_perm](/common/cmd_perm) | 本页 |

## 相关

- [cmd_perm](/common/cmd_perm)
- [运维 · 命令权限](/maintainer/operate/command-permissions)
