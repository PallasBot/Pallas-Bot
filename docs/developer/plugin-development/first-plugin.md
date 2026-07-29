# 写第一个插件

本页带你在 `local/plugins/` 创建第一个可运行的群命令插件。完成后，你会有一个使用公开 `pallas.api.*` 的插件，并了解如何声明命令权限、帮助菜单与冷却。

适合已经能在本机运行 Pallas-Bot、希望先做站点私有插件的开发者。这里先聚焦一条群命令；配置页、热载策略、正式插件骨架和发布方式可以在验收通过后再学习。

## 验收目标

群内发送 **牛牛你好** → Bot 回复一句问候；**牛牛帮助** 里出现本插件，且「何人可用」与代码声明一致。

<ChatPanel title="验收时的群聊示意">
<ChatMessage nickname="群友">牛牛你好</ChatMessage>
<ChatMessage nickname="牛牛">你好，这里是 hello_pallas 示例插件。</ChatMessage>
<ChatMessage nickname="群友">牛牛帮助</ChatMessage>
<ChatMessage nickname="牛牛">（帮助图里出现「你好牛牛」，并展示何人可用）</ChatMessage>
</ChatPanel>

## 开始前

| 项 | 要求 |
| --- | --- |
| 环境 | 本机已能运行 Pallas-Bot（见 [五分钟跑起来](/guide/quickstart)） |
| 目录 | 仓库根下存在或将创建 `local/plugins/` |
| API | 只 import `pallas.api.*`；勿用 `pallas.core.*` 或旧 `src.*` |

`config/pallas.toml` 显式声明插件目录（未配置时主线也会扫描 `local/plugins/`）：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

## 推荐学习路径

1. 按下面步骤创建并加载 `hello_pallas`，先完成验收目标。
2. 需要增加命令、参数或常见交互时，查 [Cookbook](pallas-api-cookbook.md)。
3. 需要插件配置页或调整热载方式时，读 [配置与 WebUI](config-and-webui.md) 与 [Reload 与 Activation](/developer/plugin-development/reload-and-activation)。
4. 准备长期维护、内置或独立发布插件时，再使用 [Golden Plugin](golden-plugin.md)、[发布](publishing.md) 和 [社区插件作者](/guide/community-plugin-author)。

本页的 `README.md` 是最小说明；社区商店详情页会读取它。WebUI 配置、独立仓 / PyPI、社区商店发布都不是完成第一个插件的前提。

---

## 步骤 1：创建插件目录

在仓库根下建立如下结构。目录名 `hello_pallas` 即包名，后续 import 与命令 ID 前缀都与之对齐。

```text
local/plugins/hello_pallas/
├── __init__.py
├── handlers.py
└── README.md
```

## 步骤 2：编写 `__init__.py`

声明 `PluginMetadata`（权限、冷却、帮助菜单）、注册群命令 matcher、绑定 handler。写入 `local/plugins/hello_pallas/__init__.py`：

```python
from nonebot.plugin import PluginMetadata

from pallas.api.commands import bind_alias_handlers, group_command
from pallas.api.limits import command_limit_list, command_limit_row
from pallas.api.metadata import SCENE_GROUP, join_usage, usage_line
from pallas.api.perm import command_perm_list, command_perm_row

from .handlers import handle_hello

__plugin_meta__ = PluginMetadata(
    name="你好牛牛",
    description="示例：群内打招呼。",
    usage=join_usage(usage_line("牛牛你好", "回一句问候。")),
    type="application",
    supported_adapters={"~onebot.v11"},
    extra={
        "command_permissions": command_perm_list(
            command_perm_row("hello_pallas.hello", "牛牛你好", "everyone"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("hello_pallas.hello", 3),
        ),
        "menu_data": [
            {
                "func": "打招呼",
                "trigger_method": "命令",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛你好",
                "brief_des": "回一句问候。",
                "detail_des": "群内发送「牛牛你好」。",
                "command_permission": "hello_pallas.hello",
            },
        ],
        "reload_policy": "config_only",
    },
)

cmd = group_command("hello_pallas.hello", "牛牛你好")
bind_alias_handlers(cmd, handle_hello)
```

要点：`hello_pallas.hello` 在 `command_permissions`、`command_limits`、`menu_data.command_permission` 与 `group_command` 四处必须一致，帮助图才会正确展示「何人可用」。

## 步骤 3：编写 `handlers.py`

handler 里处理冷却与回复正文。冷却秒数与 `command_limits` 中的 `3` 对应。

```python
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher

from pallas.api.limits import is_command_cooldown_ready, refresh_command_cooldown

COMMAND_ID = "hello_pallas.hello"
CD_SEC = 3


async def handle_hello(matcher: Matcher, event: GroupMessageEvent) -> None:
    if not await is_command_cooldown_ready(event, COMMAND_ID, CD_SEC):
        return
    await refresh_command_cooldown(event, COMMAND_ID, CD_SEC)
    await matcher.finish(Message("你好，这里是 hello_pallas 示例插件。"))
```

## 步骤 4：写最小 README

`README.md` 写明用途、命令、额外依赖，并说明默认权限以 WebUI「命令权限」为准。

## 步骤 5：加载并验收

1. 重启 Bot（或按站点 activation 策略热载代码）。
2. 测试群发送 **牛牛你好** → 问候回复。
3. 发送 **牛牛帮助** → 帮助图出现「你好牛牛」，「何人可用」与 `everyone` 一致。
4. WebUI **命令权限** → 矩阵出现 `hello_pallas.hello`。

## 常见失败

| 现象 | 可能原因 |
| --- | --- |
| 发命令无响应 | 目录未在 `extra_plugin_dirs`、包名与目录不一致、或改代码后未重启 |
| 启动报 import 错 | 写了 `pallas.core.*` 或历史 `src.*` 路径 |
| 帮助图无「何人可用」 | `menu_data` 未绑 `command_permission`，或 ID 与 matcher 不一致 |
| 帮助里写死了「仅群管」等 | 违反 cmd_perm 约定；权限只走 metadata，文案勿写死角色 |

## 相关

| 目标 | 文档 |
| --- | --- |
| 配置页与热载 | [配置与 WebUI](config-and-webui.md) |
| 正式目录骨架 | [Golden Plugin](golden-plugin.md) |
| 权限细则 | [cmd_perm](/common/cmd_perm) |
| 独立仓 / PyPI | [发布](publishing.md)、扩展模板 `templates/pallas-plugin-extension/` |
| 社区商店示例 | [pallas-community-plugin-interact](https://github.com/TogetsuDo/pallas-community-plugin-interact) |
| 入门 / Cookbook / 测试 | [入门](getting-started.md) · [Cookbook](pallas-api-cookbook.md) · [测试](testing.md) |
