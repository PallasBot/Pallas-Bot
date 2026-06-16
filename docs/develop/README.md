# 开发指南

面向 **Pallas-Bot**、**Pallas-Bot-WebUI** 或站点插件维护者。部署见 [五分钟跑起来](../guide/quickstart.md)、**[4.0 启动说明](../guide/4.0-start.md)**、[使用指南](../user/README.md)。

## 阅读顺序

| 文档 | 说明 |
| --- | --- |
| **[插件 Cookbook · 牛牛赞我](plugin/cookbook.md)** | **推荐首读**：跟做完整插件（配置、落盘、CD、测试、文档） |
| [本地开发环境](environment.md) | `uv`、配置、启动、分片 |
| [贡献与提交流程](workflow.md) | Ruff、pre-commit、测试、PR |
| [插件开发入门](plugin/getting-started.md) | 最小骨架速览 |
| [插件结构](plugin/structure.md) | 目录、`data/` / `resource/` |
| [插件进阶](plugin/advanced.md) | cmd_perm、热重载、审查 |
| [插件 Skill（Agent）](../skills/pallas-plugin-development/SKILL.md) | Matcher、scrub 等分章专题 |
| [WebUI 前端](webui.md) | 独立仓联调、窄屏 |

## 延伸阅读

| 文档 | 说明 |
| --- | --- |
| [项目结构](../architecture/project-structure.md) | 顶层与 `src/` 分层 |
| [插件规范](../architecture/plugin-convention.md) | `src/plugins` 约定 |
| [站点定制](../architecture/site-customization-and-updates.md) | `local/plugins`、官方扩展 |
| [4.0 路线图](../architecture/pallas-4.0-roadmap.md) · [瘦身迁移](../architecture/pallas-4.0-slim.md) | core / extra |
| [Core 开发体验路线](../architecture/core-devx-roadmap.md) | plugin_sdk、`pb_core`、M5 `pb_webui`/`pb_protocol` 改名 |
| [Bot ↔ AI 仓](../architecture/pallas-ai-service.md) | LLM 协同 |
| [cmd_perm](../common/cmd_perm/README.md) · [command_limits](../common/command_limits/README.md) | 权限与冷却 |
| [WebUI 配置](../common/webui/README.md) · [message_scrub](../common/message_scrub/README.md) | 热重载与审查 |

约定汇总：[AGENTS.md](https://github.com/PallasBot/Pallas-Bot/blob/main/AGENTS.md)、[CONTRIBUTING.md](https://github.com/PallasBot/Pallas-Bot/blob/main/CONTRIBUTING.md)。正文以 **主仓 `docs/`** 为源，同步至 [在线文档](https://PallasBot.github.io/Pallas-Bot-Docs/)。
