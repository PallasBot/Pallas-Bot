# 运维入口

## 按目标跳转

| 目标 | 文档 |
| --- | --- |
| 本机首次跑通 | [快速开始](/guide/quickstart) · [源码安装](/guide/install-source) · [Docker](/deploy/docker) |
| 安装决斗 / MAA / 协议端 / AI | [安装插件](/guide/install-plugins) · [AI 扩展](/guide/ai) |
| Docker | [Docker 部署](/deploy/docker) |
| 单进程长跑 | [单进程部署](/maintainer/deploy/single-process) |
| 多账号 / 分片 | [分片部署](/maintainer/deploy/sharded) |
| 版本升级 | [升级](/maintainer/deploy/upgrade) · [3.x → 4.0 迁移](/guide/4.0-migration) |
| 新装验收 | [安装验收 Checklist](/maintainer/install/ga-install-checklist) |
| 排障 | [排障](/maintainer/operate/troubleshooting) |
| 闲聊 / 记忆异常 | [LLM 与 AI](/maintainer/operate/llm-and-ai) |
| 配置键查询 | [配置参考](/maintainer/reference/config) |

## 组件安装

| 组件 | 文档 |
| --- | --- |
| Pallas-Bot 本体 | [本体安装](/maintainer/install/bot) |
| WebUI | [WebUI](/maintainer/install/webui) |
| 协议端 | [协议端](/maintainer/install/protocol) |
| 官方插件 | [官方插件](/maintainer/install/official-extensions) |
| AI Runtime | [AI Runtime](/maintainer/install/ai-runtime) |
| 命令权限 | [命令权限](/maintainer/operate/command-permissions) |
| Web 控制台 | [Web 控制台](/maintainer/operate/webui) |

## 分片适用条件

多 Bot 账号同时在线、单进程资源瓶颈、或需独立 worker 协调时，参见 [分片部署](/maintainer/deploy/sharded)。默认单进程即可。
