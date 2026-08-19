# 运维入口

本页帮助安装、运行并维护 Pallas-Bot。首次部署按下面的顺序完成；已在运行的实例可直接按任务进入对应页面。

## 推荐顺序

1. 先用 [快速开始](/guide/quickstart) 跑通实例。非 Docker 长期运行优先使用[本体 Release 部署包](/maintainer/install/bot#release-部署包推荐)；需要修改代码时看[源码安装](/guide/install-source)，使用容器时看 [Docker 部署](/maintainer/deploy/docker)。
2. 按需安装 [WebUI](/maintainer/install/webui)、[协议端](/maintainer/install/protocol) 和 [官方插件](/maintainer/install/official-extensions)。需要决斗、MAA 或其他扩展时，看 [安装插件](/guide/install-plugins)；接入 AI 时，看 [AI 扩展](/guide/ai) 和 [AI Runtime](/maintainer/install/ai-runtime)。
3. 完成配置与权限：用 [命令权限](/maintainer/operate/command-permissions) 管理命令可用范围，用 [Web 控制台](/maintainer/operate/webui) 管理运行中的实例。
4. 上线前按 [安装验收 Checklist](/maintainer/install/ga-install-checklist) 检查；长期运行默认用 [单进程部署](/maintainer/deploy/single-process)（可带 Embedding 辅进程）。

## 按当前任务

| 任务 | 说明 |
| --- | --- |
| 安装 Pallas-Bot 本体 | [本体安装](/maintainer/install/bot) 说明 Release 部署包、基础组件和首次启动。 |
| 使用 Docker | [Docker 部署](/maintainer/deploy/docker) 说明容器部署和运行方式。 |
| 升级现有实例 | [升级](/maintainer/deploy/upgrade) 说明常规升级步骤；从 3.x 升级时，先看 [3.x → V4 迁移](/guide/4.0-migration)。 |
| 查询配置键 | [配置参考](/maintainer/reference/config) 按配置项查找含义和用法。 |
| 处理运行问题 | [排障](/maintainer/operate/troubleshooting) 按现象定位常见运行问题；LLM 对话或记忆异常时，看 [LLM 与 AI](/maintainer/operate/llm-and-ai)。 |

## 后续阅读：多账号与分片

默认 **unified + 辅进程**（如本机 Embedding 的 `bot_embed`）即可；`uv run pallas status` / `pallas logs` 不必先学 worker-N。多个 Bot 账号同时在线且单进程已验证瓶颈、或需要强隔离时，再阅读 [分片部署](/maintainer/deploy/sharded)。
