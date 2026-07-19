# 二、Matcher 决策树

Pallas 插件在 `__init__.py` 用 **NoneBot2 Matcher**（`on_command` / `on_message` 等）注册 handler。先选对触发方式，再接 `cmd_perm` 与（按需）`message_scrub`。

## 2.1 决策流程

```
需要用户明确说一条口令？
├─ 是 → 群专属还是私聊也可？
│   ├─ 仅群 → on_command + group_message_permission_for_command
│   ├─ 仅私聊 → on_command + private_message_permission_for_command
│   └─ 两者 → 两个 matcher 或 permission_for_command + 事件类型判断
├─ 否 → 是否监听每条群消息 / 被动接话？
│   ├─ 是（复读、接话、关键词）→ on_message（常 block=False）+ 考虑 message_scrub
│   ├─ 是（进群/退群/撤回等通知）→ on_notice
│   └─ 是（好友/入群申请）→ on_request（参考 request_handler）
└─ 定时 / 启动逻辑 → APScheduler 或 driver.on_startup（见 foundation apscheduler_runtime）
```

## 2.2 触发方式对照

| Matcher | 典型场景 | 仓库示例 | cmd_perm |
| --- | --- | --- | --- |
| `on_command` | 用户主动口令、帮助、管理命令 | `greeting`、`help`、`duel` | **推荐**：matcher `permission=` |
| `on_message` | 被动接话、关键词、无固定前缀 | `repeater`、`chat`、`dream` | 多在 handler 内判断或无需 |
| `on_notice` | 群通知（撤回、成员变动） | `repeater`（撤回联动） | 通常不需要命令 ID |
| `on_request` | 加群/好友申请 | `request_handler` | 按业务 |
| `on_metaevent` / 适配器事件 | 戳一戳、特殊 meta | `greeting`（poke） | 按业务 |

## 2.3 口令型：`plugin_sdk`（推荐）

新插件优先 [`pallas.api.commands`](../../../pallas/api/commands/__init__.py) 组合 API，避免手写 perm/CD：

```python
from pallas.api.commands import bind_alias_handlers, group_command

praise = group_command("praise_me.praise", "牛牛赞我", cd_sec=0)

@praise.handle()
async def handle_praise(ctx):
    await ctx.finish("...")
```

- 群内 / 私聊 / 两者：``group_command`` / ``private_command`` / ``message_command(scene="both")``。
- 别名：``bind_alias_handlers(primary, handler)``。
- 仍可直接 ``on_command`` + ``group_message_permission_for_command``（legacy 与被动场景）。

## 2.4 `on_command` 要点（裸写时）

```python
from nonebot import on_command
from pallas.api.perm import group_message_permission_for_command

cmd = on_command(
    "帮助",
    aliases={"help"},
    priority=5,
    block=True,  # 处理成功后阻断后续 matcher
    permission=group_message_permission_for_command("help.help"),
)
```

- **`priority`**：数字越小越先匹配；被动插件常用较高数字（如 99）避免抢命令。
- **`block=True`**：命令型功能默认 `True`；被动监听常用 `False`。
- **aliases**：与主命令共享同一 matcher 与权限 ID。

## 2.5 `on_message` 要点

用于**无固定口令**或**每条消息都要看**的逻辑：

```python
from nonebot import on_message
from nonebot.rule import to_me

chat = on_message(rule=to_me(), priority=99, block=False)
```

仓库内惯例：

- **复读 `repeater`**：`on_message` + 学习/回复 gate；部分 matcher `block=False` 避免挡住其它插件。
- **做梦 `dream`**：入站先经 `message_scrub`；长文本生成类。
- **聊天 `chat`**：关键词 + 冷却（`GroupConfig.is_cooldown`）。

**慎用**：`on_message` 无过滤时会增加每条消息的 CPU；应用 `rule`（`to_me`、自定义 rule）收窄范围。

## 2.6 入站审查（message_scrub）

复读、做梦等插件在消费用户文本前，应登记 [message_scrub](../../common/message_scrub/README.md) hook，统一过滤广告/风控，而不是每个插件各自写正则。

决策：

- 插件会**大量读用户原文**并学习/生成 → **应接** message_scrub
- 纯 `on_command` 且只解析命令参数 → 通常不必

## 2.7 冷却（CD）

Pallas 提供 **`pallas.api.limits`**，在 `GroupConfig` / `BotConfig` 之上统一冷却 key（`cmd_limit:{command_id}`）。

### metadata 声明（推荐）

```python
extra={
    "command_limits": [
        {"id": "my_plugin.demo", "cd_sec": 10},
    ],
}
```

### handler 内检查

```python
from pallas.api.limits import is_command_cooldown_ready, refresh_command_cooldown

if not await is_command_cooldown_ready(event, "my_plugin.demo", 10):
    return
await refresh_command_cooldown(event, "my_plugin.demo", 10)
```

- 群消息：按群冷却（`GroupConfig`）
- 私聊：按 Bot + 用户（`BotConfig`）

详见 [command_limits 说明](../../common/command_limits/README.md)。历史插件仍可直接用 `GroupConfig.is_cooldown`；新插件优先用上述 helper 保持 key 一致。

## 2.8 分片与多牛（进阶）

多进程分片或中央入站调度下，部分插件需声明 shard 行为或走 ingress gate。涉及：

- `ingress_gate` 插件
- `docs/developer/architecture/shard-runtime.md`
- `docs/maintainer/deploy/sharded.md`

**默认新插件**按单 matcher 编写即可；只有「全群消息洪峰」「多牛同群」类功能才需提前读上述文档。

## 2.9 自检

- [ ] 能用 `on_command` 的口令型功能没有用宽泛 `on_message`
- [ ] `on_message` 已设合理 `priority` / `block` / `rule`
- [ ] 命令型已绑 `command_permissions` 与 matcher `permission`
- [ ] 被动文本类已评估 message_scrub
- [ ] 高频路径避免同步阻塞与巨型 handler

## 2.10 下一步

- 权限与帮助文案 → [三、cmd_perm](./03-cmd-perm-and-help.md)
- WebUI 配置 → [四、WebUI 配置](./04-webui-config.md)
