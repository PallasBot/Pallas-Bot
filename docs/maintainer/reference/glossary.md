# 术语表

运维文档中的高频术语。开发向归属判定见 [Core 与扩展](/developer/architecture/core-vs-extensions)。

## Core

主仓默认提供的平台能力、本体运行时和内置插件。

## Official Extension

官方维护、以独立扩展包形式安装和发布的能力。

## Community Extension

第三方或站点私有扩展，不属于主仓默认能力，也不一定属于官方发版体系。

## WebUI

控制台前端与其后端接口的统称。前端源码在 `Pallas-Bot-WebUI`；主仓默认运行产物在 `data/pb_webui/public-react/`。

## Protocol Runtime

把 QQ 或协议侧连接带进 Pallas 运行时的部分，例如 NapCat。

## AI Runtime

`Pallas-Bot-AI` 承担的媒体任务与遗留 RWKV 执行环境。普通 `@` 聊天走 Bot Provider，不依赖本 Runtime。

## Provider

Bot 侧配置的 LLM 接入（侧栏 **AI 配置 → 接入**）。用于普通聊天、工具循环与相关推理。

## Hub

分片模式下的协调与聚合入口，不是主要的消息处理位置。

## Worker

分片模式下实际运行大多数消息处理和插件逻辑的进程。

## `reload_policy`

作者视角的热重载粒度：配置、元数据或代码变更边界。

## `activation_policy`

维护者视角的生效方式：安装或更新扩展后是否需要重启、重启哪一层。

## 相关阅读

- [分片部署](/maintainer/deploy/sharded)
- [Reload 与 Activation](/developer/plugin-development/reload-and-activation)
- [LLM 对话、媒体与 AI Runtime](/guide/ai-runtime-choice)
