# 插件治理

插件治理覆盖声明、配置、生效与可见性；入口分散在 metadata、WebUI API 与 CLI。

## 治理面

| 面 | 载体 | 作用 |
| --- | --- | --- |
| `reload_policy` | `PluginMetadata.extra` | 配置 / 元数据变更的热载粒度 |
| `activation_policy` | 扩展矩阵 / 社区注册 | 安装·升级·卸载后的生效动作 |
| `command_permissions` | `extra` + WebUI 覆盖 | 命令默认等级与运行时覆盖 |
| `command_limits` | `extra` | 冷却声明 |
| 帮助可见性 | `usage` / `menu_data` / `help_audience` | 帮助图与控制台展示 |
| 安装 / 禁用 / 更新 | console / CLI | 包生命周期 |

## 稳定约定

| 约定 | 说明 |
| --- | --- |
| `command_permissions` + `command_limits` | 命令治理基础；命令 ID 必须稳定 |
| `reload_policy` ≠ `activation_policy` | 见 [Reload 与 Activation](/developer/plugin-development/reload-and-activation) |
| 无完整 metadata | 难以进入帮助与治理页 |

## 分层差异

| 层 | 默认假设 |
| --- | --- |
| Core | 强 Golden 结构；随主仓版本 |
| Official | 声明 `activation_policy`；PyPI 发版 |
| Community | 公开 API；索引 / Git / 本地接入 |

## 平台入口

| 能力 | 位置 |
| --- | --- |
| reload 执行 | `pallas.core.plugin_reload` |
| 官方插件 activation 表 | `pallas.core.platform.bot_runtime.plugin_matrix.OFFICIAL_EXTENSION_ACTIVATION_POLICY` |
| WebUI 插件治理 API | `packages/pb_webui` / `pallas.console.webui` |
| 元数据声明写法 | [元数据](/developer/plugin-development/metadata) |

## 演进中

- 单插件治理页展示细节
- 社区插件画像分层
- 更细的装包后自动生效策略

## 热重载与装包

配置 / 元数据 / 代码三级，以及 `reload_policy` 与 `activation_policy` 对照，见 [Reload 与 Activation](/developer/plugin-development/reload-and-activation)。

运维检查清单：[热重载前检查](/maintainer/operate/hot-reload-pre-reload-checklist)。

## 相关

- [Core 与扩展](core-vs-extensions.md)
- [元数据](/developer/plugin-development/metadata)
- [Reload 与 Activation](/developer/plugin-development/reload-and-activation)
- [Golden Plugin](/developer/plugin-development/golden-plugin)
