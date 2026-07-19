# 插件开发入门

推荐顺序：创建插件 → 元数据 → 发布（对齐 NoneBot 路径）。

## 路径

| 步骤 | 文档 |
| --- | --- |
| 1. 跟做最小插件 | **[写第一个插件](first-plugin.md)** |
| 2. 定骨架 | [Golden Plugin](golden-plugin.md) |
| 3. 公开 API | [pallas.api Cookbook](pallas-api-cookbook.md) |
| 4. 配置 / 权限 / 元数据 | [配置与 WebUI](config-and-webui.md) · [cmd_perm](/common/cmd_perm) · [元数据](metadata.md) |
| 5. 测试与发布 | [测试](testing.md) · [发布](publishing.md) |

## 放置位置

| 类型 | 路径 |
| --- | --- |
| 站点私有 / 试验 | `local/plugins/`（首插件从这里开始） |
| 内置 core | `packages/` |
| 官方 / 社区扩展 | 独立仓库 |

## 完成定义

| 项 | 要求 |
| --- | --- |
| API | 社区扩展只 import `pallas.api.*` |
| 入口 | `__init__.py` 薄；逻辑在 `handlers.py` |
| 权限 / 帮助 | `command_permissions` + `menu_data`；文案不写死角色 |
| 配置 | 有插件页则 `install_hot_reload_config` |
| 测试 / README | 最小 metadata 测试 + README |

## 硬约束

| MUST | MUST NOT |
| --- | --- |
| `pallas.api.*` | `pallas.core.*` / 旧 `src.*`（社区） |
| 命令 ID 全链路一致 | 帮助文案写死「仅群管」等 |
| 配置走统一热载 | 模块级长期缓存 `get_config()` |

## 相关

- [写第一个插件](first-plugin.md)
- [Golden Plugin](golden-plugin.md)
- [Developer 入口](/developer/index)
