# Pallas-Bot 文档

> 在线阅读：[Pallas-Bot-Docs](https://PallasBot.github.io/Pallas-Bot-Docs/)

先按下面的入口找到当前要完成的事。第一次安装时，不需要把所有页面看完。

## 从当前任务开始

| 当前要做的事 | 从这里开始 |
| --- | --- |
| 第一次装 | [快速开始](guide/quickstart.md) |
| 要装插件 | [安装插件](guide/install-plugins.md) |
| 想了解消息为何更快、更稳 | [核心概念与统一消息入口](guide/concepts.md) |
| 配聊天或媒体能力 | [LLM 对话、媒体与 AI Runtime](guide/ai-runtime-choice.md) |
| 号主 / VPS 运维 | [运维入口](maintainer/quickstart.md) |
| 插件作者 | [Developer](developer/index.md) |
| 在群里查看命令 | [命令与功能](guide/usage.md) |

## 第一次使用的顺序

1. [快速开始](guide/quickstart.md)：选择源码或 Docker，启动 Bot 并登录控制台。
2. [连接 QQ](guide/connect-qq.md)：让机器人账号上线并验证群消息。
3. [号主](guide/bot-owner.md)：为每只机器人配置日常管理人。
4. 按需 [安装插件](guide/install-plugins.md) 或配置 [聊天、媒体与 AI Runtime](guide/ai-runtime-choice.md)。

只想让 `@牛牛` 聊天时，配置 Provider 即可，不需要 Pallas-Bot-AI。唱歌、TTS 和遗留 RWKV 才需要额外的 AI Runtime。

## 继续阅读

| 页面 | 适合什么时候看 |
| --- | --- |
| [Docker 部署](maintainer/deploy/docker.md) | 需要完整的容器部署与日常命令 |
| [网页控制台](guide/web-console.md) | 已启动 Bot，准备管理账号、插件和配置 |
| [运维入口](maintainer/quickstart.md) | 准备升级、排障或运行多个进程 |
| [写第一个插件](developer/plugin-development/first-plugin.md) | 准备开发站点或社区插件 |

::: tip
在线站由主仓 `docs/` 同步到 [Pallas-Bot-Docs](https://PallasBot.github.io/Pallas-Bot-Docs/)。  
上手看 `guide/`，部署和排障看 `maintainer/`，开发看 `developer/`。
:::
