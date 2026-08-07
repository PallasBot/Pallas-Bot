# Developer

本页帮助你准备开发环境、完成第一个插件，并在需要时了解主仓运行边界。日常部署与运行维护见 [运维入口](/maintainer/quickstart)。

## 推荐顺序

1. 从 [本地开发环境](/developer/environment) 准备 uv、CLI、配置和质量检查。
2. 跟随 [写第一个插件](/developer/plugin-development/first-plugin) 在 `local/plugins` 创建最小可运行插件。
3. 继续阅读 [插件开发入门](/developer/plugin-development/getting-started)，再根据需要接入 [配置](/developer/plugin-development/config-and-webui)、[元数据](/developer/plugin-development/metadata) 和 [发布](/developer/plugin-development/publishing)。
4. 开始贡献前阅读 [贡献流程](/developer/workflow)，了解分支、检查和 PR 要求。

## 按开发任务

| 任务 | 文档 | 用途 |
| --- | --- | --- |
| 编写社区或站点插件 | [写第一个插件](/developer/plugin-development/first-plugin) · [插件开发入门](/developer/plugin-development/getting-started) · [发布](/developer/plugin-development/publishing) | 从本地插件开始，并完成打包发布。 |
| 编写官方插件 | [Core vs 扩展](/developer/architecture/core-vs-extensions) · [Golden Plugin](/developer/plugin-development/golden-plugin) · [元数据](/developer/plugin-development/metadata) | 确认组件归属，按标准结构接入插件。 |
| 接入命令与权限 | [cmd_perm](/common/cmd_perm) | 定义命令权限，并让帮助展示正确的可用范围。 |
| 查询插件 API | [Cookbook](/developer/plugin-development/pallas-api-cookbook) | 查找 `pallas.api.*` 的常用调用方式。 |
| 开发或联调控制台 | [WebUI 前端](/developer/webui) · [WebUI API](/common/webui/api/) | 了解 Pallas-Bot-WebUI 的联调、构建和 JSON API 分域。 |
| 发布官方包 | [官方插件 PyPI](/developer/extension-pypi-publish) | 发布 `pallas-plugin-*` 或 `pallas-core`。 |

## 后续阅读：架构与稳定边界

| 边界 | 约定 |
| --- | --- |
| 能力分层 | `core` / `official extension` / `community extension` |
| 插件公开 API | 仅 `pallas.api.*`（社区强制） |
| WebUI | 源码在 `Pallas-Bot-WebUI`；主仓默认运行产物为 `data/pb_webui/public-react/` |
| AI | `Pallas-Bot-AI` 可选；产品语义在主仓 |
| 配置合并 | `pallas.toml` → `.env` → `webui.json` |
| 分片 | hub / worker / Redis；消息主路径在 worker |

主仓或平台开发时，可按 [架构总览](/developer/architecture/overview) → [Bot 内置 Agent 生命周期](/developer/architecture/agent-lifecycle) → [LLM 输出路径](/developer/architecture/llm-output-path) → [分片](/developer/architecture/shard-runtime) → [配置存储](/developer/architecture/config-storage) → [治理](/developer/architecture/plugin-governance) 的顺序阅读。

## 后续阅读：目录索引

| 区 | 内容 |
| --- | --- |
| [architecture/](/developer/architecture/overview) | 运行时、分层、分片、配置、治理 |
| [plugin-development/](/developer/plugin-development/first-plugin) | 首插件、骨架、元数据、配置、测试、发布 |
| [reference/](/developer/reference/repo-layout) | 仓库布局、API 分层、控制台约定 |

补充索引：[Author](/developer/author/index)。
