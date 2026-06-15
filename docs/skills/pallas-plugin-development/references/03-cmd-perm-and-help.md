# 三、cmd_perm 与帮助文案

实现包：`src/features/cmd_perm/`。人类向细则：[cmd_perm/README.md](../../common/cmd_perm/README.md)。

## 3.1 命令 ID 规则

- 格式：`{插件包名}.{动作}`，例如 `duel.start`、`help.help`
- **同一 ID** 必须出现在：
  - `extra["command_permissions"]`
  - matcher 的 `permission_for_command(...)` 或合并 helper
  - `menu_data` 的 `command_permission` / `command_permissions`
- WebUI「命令权限」矩阵与帮助图「何人可用」都依赖这套 ID

## 3.2 默认等级

在 `PluginMetadata.extra` 声明：

```python
"command_permissions": [
    {"id": "my_plugin.demo", "label": "牛牛示例", "default": "everyone"},
    {"id": "my_plugin.admin", "label": "管理操作", "default": "group_moderator"},
],
```

| `default` 值 | 含义 |
| --- | --- |
| `everyone` | 不额外限制（仍受群/私聊场景约束） |
| `bot_moderator` | 号主 |
| `group_moderator` | 群管/群主 |
| `staff` | 群管或号主 |
| `superuser` | 超管 |

运行中可由 WebUI 覆盖（`webui.json` → `PALLAS_COMMAND_PERMISSION_OVERRIDES`），**通常无需重启**。

## 3.3 Matcher 权限 helper

```python
from src.features.cmd_perm import (
    group_message_permission_for_command,
    private_message_permission_for_command,
    permission_for_command,
)

# 仅群消息
on_command("群内", permission=group_message_permission_for_command("my_plugin.in_group"))

# 仅私聊
on_command("私聊", permission=private_message_permission_for_command("my_plugin.in_private"))

# 群+私聊同一等级
on_command("通用", permission=permission_for_command("my_plugin.any"))
```

**禁止** `Permission & permission_for_command(...)` 叠 Permission；用上述合并 helper。

## 3.4 handler 内手动鉴权

Matcher 无法表达时（例如一条 handler 内分支）：

```python
from src.features.cmd_perm import satisfies_command_permission

if not await satisfies_command_permission(bot, event, "my_plugin.action"):
    return
```

## 3.5 帮助 `usage` 与 `menu_data`

### `usage`（PluginMetadata.usage）

```python
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line

usage=join_usage(
    usage_line("牛牛帮助", "查看帮助"),
    usage_line("牛牛状态", "查看状态"),
),
```

- ≥2 条时 `join_usage` 自动编号
- `description` 一句句号结尾
- **不要在 usage 末尾写**「仅群管可用」——帮助图会根据权限**自动**展示「何人可用」

### `menu_data`（二级/三级帮助图）

```python
"menu_data": [
    {
        "func": "牛牛示例",
        "trigger_method": "on_command",      # 或 on_message 等，与真实 matcher 一致
        "trigger_scene": SCENE_GROUP,        # SCENE_GROUP / SCENE_PRIVATE / SCENE_AUTO
        "trigger_condition": "牛牛示例",     # 只写怎么说，不写权限
        "command_permission": "my_plugin.demo",
        "brief_des": "简短说明。",
        "detail_des": "详情；与权限无关的前提写在这里。",
    },
],
```

多命令绑同一菜单项时用 `command_permissions` 列表。

### 与 cmd_perm 无关的条件

例如「须本 Bot 为 QQ 群管理员」→ 写在 `detail_des` 或 `docs/plugins/<name>/README.md`，**不要**塞进 `usage` / `trigger_condition`。

## 3.6 metadata 模板字段

与仓库其它插件对齐：

```python
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)

extra={
    "version": PLUGIN_EXTRA_VERSION,
    "menu_template": PLUGIN_MENU_TEMPLATE,
    "homepage": PLUGIN_HOMEPAGE,  # 也可写在 PluginMetadata.homepage
    ...
}
```

## 3.7 插件 README 表格

开发者向文档可用表格列出**代码默认等级**，并注明以 WebUI / cmd_perm 为准。用户向 README 模板：[plugins/TEMPLATE.md](../../plugins/TEMPLATE.md)。

## 3.8 自检清单

- [ ] 每个需鉴权的 matcher 都有对应 `command_permissions` 项
- [ ] `menu_data.command_permission` 与 matcher ID 一致
- [ ] `usage` / `trigger_condition` 无写死权限角色
- [ ] 群/私聊限定用了 `group_message_permission_for_command` 等，未手写 `Permission &`
- [ ] WebUI 保存权限后，帮助图「何人可用」与实鉴权一致（改默认等级需重启或重载插件）

## 3.9 下一步

- WebUI 配置热重载 → [四、WebUI 配置](./04-webui-config.md)
- 测试与文档 → [七、测试与文档](./07-tests-and-docs.md)
