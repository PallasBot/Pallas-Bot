# 一、插件基础结构

Pallas 插件运行在 **NoneBot2** 之上，业务代码落在 `src/plugins/` 或站点 `local/plugins/`；横切能力由 `src/features`、`src/console` 等内核层提供（见 [common-layers](../../architecture/common-layers.md)）。

## 1.1 两种参与方式

| 方式 | 目录 | 适用 |
| --- | --- | --- |
| **贡献主仓** | `src/plugins/<name>/` | 可上游合并的功能 |
| **站点自有** | `local/plugins/<name>/` | 私有定制、避免与主仓 diff 混杂 |

站点插件需在 `config/pallas.toml` 配置 `extra_plugin_dirs`（指向 `local/plugins` 等），**重启后**加载。与主仓同名包时 **local 覆盖**主仓实现。

详见 [站点定制与更新](../../architecture/site-customization-and-updates.md)。

## 1.2 最小目录

```
my_plugin/
├── __init__.py    # PluginMetadata + Matcher 注册（保持轻量）
└── config.py      # 配置模型；需 WebUI 可调时接热重载
```

按需扩展：`handlers.py`、`models.py`、`services/`、`renderer.py` 等语义化模块。原则见 [plugin/structure.md](../../develop/plugin/structure.md)。

## 1.3 入口 `__init__.py` 职责

1. 定义 `__plugin_meta__`（`PluginMetadata`）
2. 创建 Matcher（`on_command` / `on_message` 等）
3. 注册 handler；复杂逻辑放到同目录其它模块

**不要**在 `__init__.py` 堆数百行业务实现。

## 1.4 命名

- 包名：小写 + 下划线，与目录名一致（`my_plugin`）
- 命令 ID：`my_plugin.action`（插件名 + 动作）
- 新增函数：非必要不要 `_` 前缀

## 1.5 公开 API（允许 import）

插件应优先从下列包导入；避免 `import` 内核深层私有模块。

| 层 | 路径 | 典型用途 |
| --- | --- | --- |
| features | `src.features.cmd_perm` | 命令权限、帮助 metadata 工具 |
| features | `src.features.message_scrub` | 复读/做梦等入站过滤登记 |
| features | `src.features.community_stats` | 在线统计（按需） |
| features | `src.features.command_limits` | 命令 CD（`cmd_limit:{id}`） |
| console | `src.console.webui` | `install_hot_reload_config` |
| foundation | `src.foundation.paths` | `plugin_data_dir`、`resource_dir` |
| foundation | `src.foundation.config` | `BotConfig` / `GroupConfig`（群级冷却等） |
| foundation | `src.foundation.db` | 持久化 repository（按需） |
| shared | `src.shared.utils` | 通用工具（按需） |

内核分层说明：[common-layers.md](../../architecture/common-layers.md)。

**反例**：从 `src.plugins.other_plugin` 直接 import 业务逻辑 → 应把共享能力下沉到 `src/features` 或 `src/foundation`。

## 1.6 最小元数据骨架

```python
from nonebot import on_command
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm import group_message_permission_for_command
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line

__plugin_meta__ = PluginMetadata(
    name="示例插件",
    description="一句话说明插件做什么。",
    usage=join_usage(usage_line("牛牛示例", "触发示例命令")),
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

完整拷贝版见 [getting-started.md](../../develop/plugin/getting-started.md)。

## 1.7 配置入口（可选）

```python
from pydantic import BaseModel, Field
from src.console.webui import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    enable: bool = Field(default=True, description="是否启用。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

业务代码始终 `get_config()`；详情见 [四、WebUI 配置](./04-webui-config.md) 与 [webui/README.md](../../common/webui/README.md)。

## 1.8 加载与发现

- 主仓 `src/plugins/`：随 Bot 启动自动发现
- `local/plugins/`：`config/pallas.toml` 的 `extra_plugin_dirs` + **重启**
- 额外 pip 包：按 `pyproject.toml` 与 NoneBot 插件机制安装，与主仓插件并列加载

## 1.9 下一步

- 选 Matcher → [二、Matcher 决策树](./02-matchers-decision.md)
- 权限与帮助 → [三、cmd_perm](./03-cmd-perm-and-help.md)
