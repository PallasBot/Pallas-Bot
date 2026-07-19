# 术语表

运维文档高频术语。

## Core

主仓默认提供的平台能力、本体运行时和内置插件能力。

## Official Extension

官方维护、但以独立扩展包形式安装和发布的能力。

## Community Extension

第三方或站点私有扩展，不属于主仓默认能力，也不一定属于官方发版体系。

## WebUI

控制台前端与其后端接口的统称。前端源码仓和主仓运行产物分离。

## Protocol Runtime

负责把 QQ 或协议侧连接带进 Pallas 运行时的部分。

## AI Runtime

`Pallas-Bot-AI` 所承担的 AI / 媒体任务执行运行时。

## Hub

分片模式下的协调与聚合入口，不是主要的消息处理位置。

## Worker

分片模式下实际运行大多数消息处理和插件逻辑的进程。

## `reload_policy`

作者视角的热重载粒度声明，关注配置、元数据和代码变更边界。

## `activation_policy`

维护者视角的生效方式声明，关注安装或更新扩展后是否需要重启、重启哪一层。

## 相关阅读

- [Core 与扩展](/developer/architecture/core-vs-extensions)
- [分片部署](/maintainer/deploy/sharded)
- [Reload 与 Activation](/developer/plugin-development/reload-and-activation)
