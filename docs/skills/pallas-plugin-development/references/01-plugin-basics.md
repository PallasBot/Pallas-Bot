# 一、插件基础结构

Pallas 插件运行在 **NoneBot2** 之上，业务代码落在 `packages/` 或站点 `local/plugins/`；横切能力由 `pallas.api.*` 等内核层提供（见 [架构总览](../../developer/architecture/overview.md)）。

## 1.1 两种参与方式

| 方式 | 目录 | 适用 |
| --- | --- | --- |
| **贡献主仓** | `packages/<name>/` | 可上游合并的功能 |
| **站点自有** | `local/plugins/<name>/` | 私有定制、避免与主仓 diff 混杂 |

站点插件需在 `config/pallas.toml` 配置 `extra_plugin_dirs`（指向 `local/plugins` 等），**重启后**加载。与主仓同名包时 **local 覆盖**主仓实现。

详见 [升级与站点定制](../../maintainer/deploy/upgrade.md)。

## 1.2 最小目录（core / 扩展通用）

```
my_plugin/
├── __init__.py    # PluginMetadata + Matcher 注册
├── config.py      # 配置；WebUI 插件页可调时接热重载
└── startup.py     # 可选：启动钩子（pb_stats、pb_webui 等）
```

按需扩展：`handlers.py`、`models.py`、`services/` 等。core 插件对照 [八、checklist · Core 插件](./08-golden-plugin-checklist.md)。

## 1.3 入口 `__init__.py` 职责

1. 定义 `__plugin_meta__`（`PluginMetadata`）
2. 创建 Matcher（`on_command` / `on_message` 等）
3. 注册 handler；复杂逻辑放到同目录其它模块

**不要**在 `__init__.py` 堆数百行业务实现。

## 1.4 命名

- 包名：小写 + 下划线，与目录名一致（`my_plugin`）
- **内核维护者向插件**：`pb_<role>`（如 `pb_core`、`pb_stats`、`pb_webui`）
- 命令 ID：`my_plugin.action`（插件名 + 动作）
- 改名时同步 `plugin_package_aliases.py` 与 `plugin_legacy_names.py`
- 新增函数：非必要不要 `_` 前缀

## 1.5 core 与 extra

| 类型 | 矩阵 | 默认加载 | 示例 |
| --- | --- | --- | --- |
| **core** | `CORE_PLUGIN_NAMES` | slim 也加载 | `repeater`、`pb_stats`、`pb_core` |
| **extra** | `EXTRA_PLUGIN_PACKAGES` | 需 `load_bundled_extra` 或 pip | `duel`、`pb_protocol` |

在线统计已升格为 core **`pb_stats`**（业务在 `pallas/product/community_stats/`；WebUI 段 ID 仍为 `community_stats`）。

## 1.6 公开 API（允许 import）

插件应优先从下列包导入；避免 `import` 内核深层私有模块。

| 层 | 路径 | 典型用途 |
| --- | --- | --- |
| api | `pallas.api.commands` | 口令注册、PluginHandlerContext |
| api | `pallas.api.perm` | 命令权限、权限 helper |
| api | `pallas.api.metadata` | 帮助文案、菜单模板常量 |
| api | `pallas.api.limits` | 命令 CD（`cmd_limit:{id}`） |
| api | `pallas.api.config` | `install_hot_reload_config` |
| api | `pallas.api.paths` | `plugin_data_dir`、`resource_dir` |
| api | `pallas.api.storage` | `GroupPluginStorage`、声明式存储 |
| api | `pallas.api.safety` | `message_scrub` 入站过滤登记 |
| core | `pallas.core.foundation.config` | `BotConfig` / `GroupConfig`（内置插件用） |
| core | `pallas.core.foundation.db` | 持久化 repository（内置插件按需） |
| product | `pallas.product.message_scrub` | 入站审查实现（内置专用） |

> **社区 / pip 扩展**：仅 `pallas.api.*`（L1）。**内置 `packages/`**：可用 `pallas.api.*` + `pallas.product.*`（L2），禁止 `pallas.core.*` 深层文件。

内核与公开 API 说明：[仓库布局](../../developer/reference/repo-layout.md)。

**反例**：从 `packages.other_plugin` 直接 import 业务逻辑 → 应把共享能力下沉到 `pallas/` 内核层。

## 1.7 最小元数据骨架

```python
from nonebot import on_command
from nonebot.plugin import PluginMetadata

from pallas.api.metadata import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
    SCENE_GROUP,
    join_usage,
    usage_line,
)
from pallas.api.perm import group_message_permission_for_command

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

现行入口见 [插件开发入门](../../developer/plugin-development/getting-started.md)。

## 1.8 配置入口（可选）

```python
from pydantic import BaseModel, Field
from pallas.api.config import install_hot_reload_config

class Config(BaseModel, extra="ignore"):
    enable: bool = Field(default=True, description="是否启用。")

plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

业务代码始终 `get_config()`；详情见 [四、WebUI 配置](./04-webui-config.md) 与 [webui/README.md](../../common/webui/README.md)。

## 1.9 加载与发现

- 主仓 `packages/`：随 Bot 启动自动发现
- `local/plugins/`：`config/pallas.toml` 的 `extra_plugin_dirs` + **重启**
- 额外 pip 包：按 `pyproject.toml` 与 NoneBot 插件机制安装，与主仓插件并列加载

## 1.10 下一步

- 选 Matcher → [二、Matcher 决策树](./02-matchers-decision.md)
- 权限与帮助 → [三、cmd_perm](./03-cmd-perm-and-help.md)
