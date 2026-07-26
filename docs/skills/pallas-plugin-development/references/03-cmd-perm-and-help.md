# 三、cmd_perm 与帮助文案

实现：`pallas/core/perm/`。人类向细则：[cmd_perm/README.md](../../../common/cmd_perm/README.md)（本页只保留 Agent 动作清单，不复述全文）。

## 3.1 命令 ID

- 格式：`{插件包名}.{动作}`（如 `duel.start`）
- **同一 ID** 出现在：`extra["command_permissions"]`、matcher `permission_*`、`menu_data.command_permission(s)`
- WebUI「命令权限」与帮助图「何人可用」都依赖这套 ID

## 3.2 默认等级与 Matcher

`default`：`everyone` | `bot_moderator` | `group_moderator` | `staff` | `superuser`。运行中可由 WebUI 覆盖（通常无需重启）。

```python
from pallas.api.perm import (
    group_message_permission_for_command,
    private_message_permission_for_command,
    permission_for_command,
    satisfies_command_permission,
)

on_command("群内", permission=group_message_permission_for_command("my_plugin.in_group"))
on_command("私聊", permission=private_message_permission_for_command("my_plugin.in_private"))
on_command("通用", permission=permission_for_command("my_plugin.any"))
# handler 内：await satisfies_command_permission(bot, event, "my_plugin.action")
```

**禁止** `Permission & permission_for_command(...)`；用合并 helper。

## 3.3 帮助文案要点

| 字段 | MUST | MUST NOT |
| --- | --- | --- |
| `usage` | `usage_line` + `join_usage`；`description` 一句句号 | 末尾写「仅群管可用」等 |
| `trigger_condition` | 只写怎么说 | 写权限角色 |
| `command_permission(s)` | 与 matcher ID 一致 | 漏绑 |
| `detail_des` / 插件 README | 与 cmd_perm 无关的前提（如本 Bot 须为 QQ 群管） | 塞进 `usage` / `trigger_condition` |

模板常量：`PLUGIN_EXTRA_VERSION` / `PLUGIN_HOMEPAGE` / `PLUGIN_MENU_TEMPLATE`（`pallas.api.metadata`）。用户向 README：[plugins/TEMPLATE.md](../../../plugins/TEMPLATE.md)。

## 3.4 自检清单

- [ ] 每个需鉴权的 matcher 都有对应 `command_permissions` 项
- [ ] `menu_data.command_permission` 与 matcher ID 一致
- [ ] `usage` / `trigger_condition` 无写死权限角色
- [ ] 群/私聊限定用了合并 helper，未手写 `Permission &`
- [ ] WebUI 保存权限后，帮助图「何人可用」与实鉴权一致（改默认等级需重启或重载插件）

## 3.5 下一步

- WebUI 配置热重载 → [四、WebUI 配置](./04-webui-config.md)
- 测试与文档 → [七、测试与文档](./07-tests-and-docs.md)
