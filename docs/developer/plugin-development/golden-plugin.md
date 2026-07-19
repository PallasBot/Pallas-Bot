# Golden Plugin

Pallas-Bot 插件默认骨架与接入约定。新增 core 插件或回迁旧插件时按本页执行。

完整 checklist（主仓）：[08-golden-plugin-checklist](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/skills/pallas-plugin-development/references/08-golden-plugin-checklist.md)。

## 目录结构

```text
packages/<name>/
├── __init__.py   # PluginMetadata + matcher 注册（薄入口，目标 ≤120 行）
├── config.py     # Pydantic + install_hot_reload_config（有插件页时）
├── handlers.py   # 口令 / 被动消息
└── startup.py    # 可选：on_startup、HTTP 挂载；hub-only 用 is_sharded_worker 守卫
```

| 文件 | MUST | MUST NOT |
| --- | --- | --- |
| `__init__.py` | `PluginMetadata`、`command_permissions` / `limits` / `menu_data`、matcher 注册 | 大段业务、复杂持久化、长启动、大段 HTTP |
| `config.py` | 模型 + `install_hot_reload_config` | import 时缓存配置快照 |
| `handlers.py` | 口令实现 | 重复声明权限默认值导致漂移 |
| `startup.py` | 仅在需要时存在 | 无守卫的 hub 侧消息逻辑 |

## 命令接入

优先 `pallas.api.commands`（与 `plugin_sdk` 同源出口）。

一条命令 MUST 对齐同一 `command_id`：

- `command_permissions`
- `menu_data`（`command_permission` / `command_permissions`）
- 可选 `command_limits`

```python
from nonebot.plugin import PluginMetadata

from pallas.api.commands import bind_alias_handlers, group_command
from pallas.api.metadata import join_usage, usage_line

from .handlers import handle_main

__plugin_meta__ = PluginMetadata(
    name="example",
    description="示例插件。",
    usage=join_usage(usage_line("示例命令", "说明。")),
    type="application",
    extra={
        "command_permissions": [
            {"id": "example.main", "label": "示例命令", "default": "everyone"},
        ],
        "command_limits": [
            {"id": "example.main", "cd_sec": 5},
        ],
        "menu_data": [
            {
                "func": "示例命令",
                "trigger_method": "命令",
                "trigger_condition": "群聊发送口令",
                "brief_des": "一句话说明。",
                "detail_des": "详细说明。",
                "command_permission": "example.main",
            },
        ],
        "reload_policy": "config_only",
    },
)

cmd = group_command("example.main", "示例命令")
bind_alias_handlers(cmd, handle_main)
```

## 配置

```python
from pydantic import BaseModel, Field

from pallas.api.config import install_hot_reload_config


class Config(BaseModel, extra="ignore"):
    enable: bool = Field(default=True, description="是否启用。")


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

业务侧每次调用 `get_config()`；禁止模块级长期快照。

## 维护者向 vs 群口令

| 类型 | 约定 |
| --- | --- |
| 维护者向（`pb_webui`、`pb_protocol`、`pb_stats` 等） | 可无群口令；`help_audience: maintainer`；说明落在 WebUI / 通用配置段 |
| 群口令插件 | `handlers.py` + 完整 `menu_data` / 权限 / 冷却 |

## 存储与路径

| 场景 | API |
| --- | --- |
| 结构化状态 | `pallas.api.storage`（`get_plugin_storage` / `set_plugin_storage`） |
| 大文件 / 缓存 / 导出 | `pallas.api.paths.plugin_data_dir` |
| 全局资源 | `pallas.api.paths.resource_dir` |

禁止硬编码散落相对路径与私有 JSON 布局。数据落 `data/<plugin_name>/`，资源落 `resource/`。

复杂度上升时按业务能力拆文件（`renderer.py`、`ban_manager.py` 等）；边界清晰后再引入 `services/`、`repositories.py`。

## 包内视觉资源（assets）

控制台插件列表、商店与帮助图共用 `resolve_catalog_visuals()`。

| 角色 | 推荐路径 |
| --- | --- |
| cover | `assets/cover.png` / `assets/cover.webp` |
| icon | `assets/icon.png` / `assets/icon.webp` |
| avatar | `assets/avatar.png` |

对外 URL：`/pallas/plugin-assets/<plugin_id>/…`。无包内文件时回退商店快照与远程 URL。

## 命令权限文案

- `usage`、`menu_data.trigger_condition` 不写死「群管 / 群主」等角色；「何人可用」由 `command_permission(s)` 与 WebUI 覆盖生成
- 与发送者权限无关的条件（如本 Bot 须为 QQ 群管）写在 `detail_des` 或插件 README

详见 [cmd_perm](/common/cmd_perm)。

## 交付物

| 项 | 路径 |
| --- | --- |
| 测试 | `tests/plugins/<name>/` |
| 文档 | `docs/plugins/<name>/README.md` |

## 提交前检查

- [ ] `__init__.py` ≤ ~120 行且无业务堆叠
- [ ] 命令 ID 在 permissions / limits / menu / matcher 一致
- [ ] 配置走 `install_hot_reload_config`（若有插件页）
- [ ] 帮助文案未写死权限角色
- [ ] 测试与 README 已同步

## 相关

- [写第一个插件](first-plugin.md)
- [配置与 WebUI](config-and-webui.md)
- [元数据](metadata.md)
- [Reload 与 Activation](reload-and-activation.md)
- [测试](testing.md)
- [插件治理](/developer/architecture/plugin-governance)
