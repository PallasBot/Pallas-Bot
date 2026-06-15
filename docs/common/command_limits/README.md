# 命令冷却（command_limits）

实现：`src/features/command_limits/`。

在 `cmd_perm` 鉴权通过后，对高频命令做**群级 / 私聊级**冷却，避免各插件手写 `GroupConfig(..., cooldown=3)` 时 key 不一致。

## metadata 声明（可选）

在 `PluginMetadata.extra` 增加 `command_limits`（与 `command_permissions` 并列）：

```python
extra={
    "command_permissions": [
        {"id": "my_plugin.demo", "label": "牛牛示例", "default": "everyone"},
    ],
    "command_limits": [
        {"id": "my_plugin.demo", "cd_sec": 10},
    ],
}
```

| 字段 | 说明 |
| --- | --- |
| `id` | 命令 ID，与 `command_permissions` / matcher 一致 |
| `cd_sec` | 冷却秒数（也可用别名 `cd`） |
| `scope` | `group` / `private` / `auto`（默认 `auto`，按事件类型选存储） |

声明供文档与后续自动拦截扩展；handler 内仍建议显式调用 helper（见下）。

## handler 内用法

```python
from src.features.command_limits import is_command_cooldown_ready, refresh_command_cooldown

CD_SEC = 10

@demo.handle()
async def handle_demo(event: GroupMessageEvent):
    if not await is_command_cooldown_ready(event, "my_plugin.demo", CD_SEC):
        return
    await refresh_command_cooldown(event, "my_plugin.demo", CD_SEC)
    await demo.finish("收到。")
```

- 群消息：冷却按 **群** 维度（`GroupConfig`）
- 私聊：按 **Bot + 用户** 维度（`BotConfig`）
- 存储 key：`cmd_limit:{command_id}`，与插件自建 `cooldown` key 隔离

## 与 cmd_perm 关系

先 `permission_for_command`（或合并 helper）拦截无权用户，再在 handler 开头做 CD。冷却未完成时通常 **静默 return** 或发简短提示，按产品约定即可。

插件开发 Skill：[Matcher 决策 · 冷却](../../skills/pallas-plugin-development/references/02-matchers-decision.md#26-冷却cd）。
