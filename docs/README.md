# Pallas-Bot 文档

> **在线阅读**：[Pallas-Bot-Docs](https://PallasBot.github.io/Pallas-Bot-Docs/)（侧栏编排更完整）

运行配置以 **`config/pallas.toml`** + **`data/pallas_config/webui.json`** 为主，见 [配置存储](architecture/settings-storage.md)。

## 认识牛牛

| 文档 | 说明 |
| --- | --- |
| [选一条路](guide/welcome.md) | 按身份选入口 |
| [理解架构（可跳过）](guide/concepts.md) | 协议端、Bot、库、控制台 |

## 快速开始

| 文档 | 说明 |
| --- | --- |
| **[4.0 启动说明](guide/4.0-start.md)** | 扩展安装、AI 仓、配置键与验收 |
| **[五分钟跑起来](guide/quickstart.md)** | 最少步骤：克隆 → 配置 → 启动 → 连 QQ |
| [使用指南](user/README.md) | 控制台入口、常用口令 |
| [配置要点](Config.md) | `pallas.toml` 与 WebUI |
| [标准部署](Deployment.md) | 生产 / VPS 分步部署 |
| [Docker 部署](DockerDeployment.md) | Compose 与卷 |
| [3.0 迁移](Migration-v3.md) | 旧版升级 |

## 查阅

| 文档 | 说明 |
| --- | --- |
| [常见问题 FAQ](FAQ.md) | 学习机制、号主、排障 |
| [插件索引](plugins/README.md) | 各功能说明与配置 |
| [社区中心](https://stats.pallasbot.top/) · [上报说明](common/community_stats.md) | 在线统计（默认开启） |

## 开发（维护者）

| 文档 | 说明 |
| --- | --- |
| [开发指南](develop/README.md) | 环境、流程、插件、WebUI |
| **[插件 Cookbook · 牛牛赞我](develop/plugin/cookbook.md)** | 跟做完整插件（推荐开发者首读） |
| [插件开发 Skill](skills/pallas-plugin-development/SKILL.md) | Agent 分章手册 |

## 架构（进阶）

| 文档 | 说明 |
| --- | --- |
| [项目结构](architecture/project-structure.md) · [内核分层](architecture/common-layers.md) | 目录与 `src/` 分层 |
| [配置存储](architecture/settings-storage.md) · [插件规范](architecture/plugin-convention.md) | 配置与插件组织 |
| [多进程分片](architecture/bot_process_sharding.md) · [入站调度](architecture/central-ingress-dispatch.md) | 分片与消息路径 |
| [多机协同与语料](architecture/control-plane-corpus-federation.md) | 联邦与社区接话库 |
| [4.0 路线图](architecture/pallas-4.0-roadmap.md) · [本体瘦身](architecture/pallas-4.0-slim.md) | 扩展分家与迁移 |
| [站点定制](architecture/site-customization-and-updates.md) | `local/plugins`、官方扩展 |

## 通用能力

[cmd_perm](common/cmd_perm/README.md) · [command_limits](common/command_limits/README.md) · [WebUI 热重载](common/webui/README.md) · [WebUI API](common/webui/api/README.md) · [message_scrub](common/message_scrub/README.md) · [语料联邦](common/corpus/README.md)

## 同步在线文档站

主仓 `docs/` 为**同步源**（见 `tools/scripts/sync_docs_to_web.py`）。合并到 `main` / `docs` 且变更 `docs/**` 时，CI 会推送到 [Pallas-Bot-Docs](https://github.com/PallasBot/Pallas-Bot-Docs)。

本地同步：

```bash
uv run python tools/scripts/sync_docs_to_web.py
```

需配置 Actions Secret `DOCS_SYNC_TOKEN` 方可自动同步，见 [sync-docs-to-web.yml](../.github/workflows/sync-docs-to-web.yml)。
