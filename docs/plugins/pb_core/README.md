# pb_core（牛牛核心）

内置运维口令：进程摘要、控制台入口、插件概览、更新检查与优雅重启。

与扩展包 **bot_status**（牛牛在吗 / 报数）分工：`pb_core.status`（**牛牛状态**）侧重版本、分片与本进程连接；在线名册仍由 bot_status 负责。

## 用户命令

| 口令 | 默认权限 | 说明 |
| --- | --- | --- |
| 牛牛状态 | staff | 版本、Git、分片角色、编排脚本、本进程已连接牛牛 |
| 牛牛控制台 | staff | WebUI 地址与登录提示 |
| 牛牛插件 | staff | 已加载 core/extra 插件概览 |
| 牛牛更新 | superuser | 只读检查 GitHub 最新 release |
| 牛牛重启 | superuser | 约 3 秒后调度 `run_*_bot.sh` 重启 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `pb_core.status` | staff |
| `pb_core.console` | staff |
| `pb_core.plugins` | staff |
| `pb_core.update_check` | superuser |
| `pb_core.restart` | superuser |

运行中可在 WebUI **命令权限** 覆盖；帮助图「何人可用」自动展示。

## 与 CLI / WebUI

- **牛牛状态** 文案与 `format_runtime_status_text()` 同源，后续可挂到 `pallas status`。
- **牛牛更新** 只读；应用更新请用 WebUI 或 `pallas update bot`。
- **牛牛重启** 与 WebUI 更新页「安装并重启」共用 `schedule_bot_restart()`。

## 实现

[`src/plugins/pb_core/`](../../../src/plugins/pb_core/) · 开发 SDK 见 [`plugin_sdk`](../../architecture/core-devx-roadmap.md#p1--plugin_sdk)
