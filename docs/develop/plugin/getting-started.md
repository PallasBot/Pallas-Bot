# 插件开发入门

Pallas-Bot 基于 **NoneBot2** + **OneBot v11**。业务插件位于 `src/plugins/<包名>/`；站点定制可放在 `local/plugins/`（见 [站点定制](../../architecture/site-customization-and-updates.md)）。

## 两种参与方式

| 方式 | 适用 | 位置 |
| --- | --- | --- |
| **贡献主仓** | 功能可上游合并 | `src/plugins/<name>/` + `docs/plugins/<name>/` + `tests/plugins/<name>/` |
| **站点自有** | 私有定制、不与上游混 diff | `local/plugins/<name>/` + `extra_plugin_dirs` |

## 最小插件骨架

每个插件至少包含：

```
src/plugins/my_plugin/
├── __init__.py    # PluginMetadata + Matcher 注册
└── config.py      # 配置模型（需 WebUI 可调时接入热重载）
```

`__init__.py` 保持轻量：声明元数据、注册 handler，业务逻辑拆到同目录其它模块。

### 元数据与帮助文案

使用 `src.common.cmd_perm.metadata_text` 统一 `usage` / `menu_data` 格式：

```python
from nonebot import on_command
from nonebot.plugin import PluginMetadata

from src.common.cmd_perm import group_message_permission_for_command
from src.common.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.common.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="示例插件",
    description="一句话说明插件做什么。",
    usage=join_usage(
        usage_line("牛牛示例", "触发示例命令"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "my_plugin.demo", "label": "牛牛示例", "default": "everyone"},
        ],
        "menu_data": [
            {
                "func": "牛牛示例",
                "trigger_method": "on_command",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛示例",
                "command_permission": "my_plugin.demo",
                "brief_des": "执行示例",
                "detail_des": "返回一条确认消息。",
            },
        ],
    },
)

demo = on_command(
    "牛牛示例",
    aliases={"示例"},
    priority=5,
    block=True,
    permission=group_message_permission_for_command("my_plugin.demo"),
)


@demo.handle()
async def handle_demo():
    await demo.finish("收到。")
```

要点：

- **`usage`**：用 `usage_line` + `join_usage`（≥2 条自动编号）；**不要**在末尾写死「群管可用」等权限句
- **`trigger_condition`**：只写**怎么说**；权限绑定 `command_permission` / `command_permissions`
- **命令 ID**：`my_plugin.demo` 在 metadata、registry、matcher 中必须一致

### 配置（可选）

```python
# config.py
from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    enable: bool = Field(default=True, description="是否启用。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_my_config = plugin_webui.get
```

业务代码通过 `get_my_config()` 读取，勿缓存 import 时的配置快照。详见 [WebUI 插件配置](../../common/webui/README.md)。

## 注册与加载

主仓插件由 NoneBot 自动发现 `src/plugins/`。`local/plugins` 需在 `config/pallas.toml` 配置 `extra_plugin_dirs` 后重启生效；**同名时 local 优先**。

## 插件文档

新增用户向插件时，在 `docs/plugins/<name>/README.md` 补充说明（可复制 [TEMPLATE.md](../../plugins/TEMPLATE.md)），并在 [plugins/README.md](../../plugins/README.md) 索引中登记。

## 测试

在 `tests/plugins/<name>/` 添加最小可验证测试，目录尽量镜像 `src/plugins/<name>/`：

```bash
uv run pytest tests/plugins/my_plugin/
```

## 下一步

- 目录拆分与路径约定：[插件结构与约定](structure.md)
- cmd_perm、热重载、消息审查、跨插件能力：[插件进阶能力](advanced.md)
- 规范总览：[插件目录约定](../../architecture/plugin-convention.md)

## 外部参考

- [NoneBot2 文档](https://nonebot.dev/)
- [OneBot v11](https://github.com/botuniverse/onebot-11)
