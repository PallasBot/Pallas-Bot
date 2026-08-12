# 二、Matcher 决策树

在 `__init__.py` 用 NoneBot2 Matcher 注册 handler。先选触发方式，再接 `cmd_perm` 与（按需）`message_scrub`。

## 2.1 决策流程

```
需要用户明确说一条命令？
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
| `on_command` | 用户主动命令 | `greeting`、`help`；官方插件如 `duel`（pip） | matcher `permission=` |
| `on_message` | 被动接话、关键词、`@` LLM 对话 | `repeater`、`llm_chat` | handler 内或无需 |
| `on_notice` | 撤回、成员变动 | `repeater` | 通常无命令 ID |
| `on_request` | 加群/好友申请 | `request_handler` | 按业务 |
| meta / 适配器事件 | 戳一戳等 | `greeting`（poke） | 按业务 |

## 2.3 命令型：`plugin_sdk`（推荐）

优先 [`pallas.api.commands`](../../../../pallas/api/commands/__init__.py)：

```python
from pallas.api.commands import group_command

hello = group_command("hello_pallas.hello", "牛牛你好", cd_sec=0)

@hello.handle()
async def handle_hello(ctx):
    await ctx.finish("你好～")
```

- 场景：`group_command` / `private_command` / `message_command(scene="both")`
- 别名：`bind_alias_handlers(primary, handler)`
- Legacy：`on_command` + `group_message_permission_for_command`

要点：`priority` 越小越先；命令型默认 `block=True`；被动常用较高 priority + `block=False`；`on_message` 用 `rule` 收窄。

## 2.4 入站审查与 CD

- 大量读用户原文学习/生成 → 接 [message_scrub](./06-message-scrub.md)（实现 `pallas/product/message_scrub/`）
- CD：`extra["command_limits"]` + `pallas.api.limits`（`cmd_limit:{command_id}`）；细则 [command_limits](../../../common/command_limits/README.md)

## 2.5 分片（进阶）

默认按单 matcher 写即可。全群洪峰 / 多牛同群再读 [分片运行时](../../../developer/architecture/shard-runtime.md)、[分片部署](../../../maintainer/deploy/sharded.md)、`ingress_gate`。

## 2.6 自检

- [ ] 命令型未滥用宽泛 `on_message`
- [ ] `on_message` 有合理 `priority` / `block` / `rule`
- [ ] 命令型已绑 `command_permissions` 与 matcher `permission`
- [ ] 被动文本类已评估 message_scrub
- [ ] 高频路径无同步阻塞

## 2.7 下一步

- 权限与帮助文案 → [三、cmd_perm](./03-cmd-perm-and-help.md)
- WebUI 配置 → [四、WebUI 配置](./04-webui-config.md)
