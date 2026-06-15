# 开发指南

面向参与 **Pallas-Bot**、**Pallas-Bot-WebUI** 或站点自有插件维护的贡献者。部署与运行配置见 [快速上手](../README.md) 与 [配置存储](../architecture/settings-storage.md)。

## 阅读顺序

| 文档 | 说明 |
| --- | --- |
| [本地开发环境](environment.md) | `uv`、配置、启动 Bot、分片与可选 Redis |
| [贡献与提交流程](workflow.md) | Ruff、pre-commit、测试、PR 与 commit 约定 |
| [插件开发入门](plugin/getting-started.md) | 新建插件、注册、最小示例 |
| [插件结构与约定](plugin/structure.md) | 目录拆分、`data/` / `resource/`、文档与测试 |
| [插件进阶能力](plugin/advanced.md) | cmd_perm、WebUI 热重载、消息审查、站点插件 |
| [插件开发 Skill（Agent）](../skills/pallas-plugin-development/SKILL.md) | 分章手册，Cursor Agent 写插件时按需加载 |
| [WebUI 前端开发](webui.md) | 独立仓库联调、窄屏与构建挂载 |

## 架构与通用能力（延伸阅读）

| 文档 | 说明 |
| --- | --- |
| [项目结构](../architecture/project-structure.md) | 顶层目录与 `src/` 内核分层 |
| [插件目录约定](../architecture/plugin-convention.md) | `src/plugins/*` 组织规范 |
| [站点定制](../architecture/site-customization-and-updates.md) | `local/plugins`、更新策略 |
| [命令权限 cmd_perm](../common/cmd_perm/README.md) | 帮助「何人可用」与 WebUI 覆盖 |
| [命令冷却 command_limits](../common/command_limits/README.md) | 统一 CD helper |
| [WebUI 插件配置](../common/webui/README.md) | `install_hot_reload_config` |
| [消息审查 message_scrub](../common/message_scrub/README.md) | 复读/做梦入站过滤 |

## 协作约定

仓库根目录 [AGENTS.md](https://github.com/PallasBot/Pallas-Bot/blob/main/AGENTS.md) 与 [CONTRIBUTING.md](https://github.com/PallasBot/Pallas-Bot/blob/main/CONTRIBUTING.md) 汇总了 Agent / 人类贡献者应遵守的约定；本文档站内容与其对齐，并以 **主仓 `docs/`** 为权威来源（同步至 [在线文档](https://PallasBot.github.io/Pallas-Bot-Docs/)）。
