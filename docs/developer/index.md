# Developer

开发者文档索引。运维见 [运维入口](/maintainer/quickstart)。

## 插件开发

| 文档 | 说明 |
| --- | --- |
| [写第一个插件](/developer/plugin-development/first-plugin) | `local/plugins` 最小可运行示例 |
| [Golden Plugin](/developer/plugin-development/golden-plugin) | 目录结构、命令接入、提交前检查清单 |
| [cmd_perm](/common/cmd_perm) | 命令权限与帮助「何人可用」 |
| [Cookbook](/developer/plugin-development/pallas-api-cookbook) | `pallas.api.*` 速查 |

## 按角色

| 角色 | 路径 |
| --- | --- |
| 社区 / 站点插件 | [首插件](/developer/plugin-development/first-plugin) → [入门](/developer/plugin-development/getting-started) → [配置](/developer/plugin-development/config-and-webui) → [发布](/developer/plugin-development/publishing) |
| 官方插件 | [Core vs 扩展](/developer/architecture/core-vs-extensions) → [Golden](/developer/plugin-development/golden-plugin) → [元数据](/developer/plugin-development/metadata) → [发布](/developer/plugin-development/publishing) |
| 主仓 / 平台 | [架构总览](/developer/architecture/overview) → [分片](/developer/architecture/shard-runtime) → [配置存储](/developer/architecture/config-storage) → [治理](/developer/architecture/plugin-governance) |

短索引：[Author](/developer/author/index)。

## 稳定边界

| 边界 | 约定 |
| --- | --- |
| 能力分层 | `core` / `official extension` / `community extension` |
| 插件公开 API | 仅 `pallas.api.*`（社区强制） |
| WebUI | 源码在 `Pallas-Bot-WebUI`；主仓 `data/pb_webui/public/` 为运行产物 |
| AI | `Pallas-Bot-AI` 可选；产品语义在主仓 |
| 配置合并 | `pallas.toml` → `.env` → `webui.json` |
| 分片 | hub / worker / Redis；消息主路径在 worker |

## 环境与协作

| 文档 | 说明 |
| --- | --- |
| [本地开发环境](/developer/environment) | uv、CLI、配置与质量门禁 |
| [贡献流程](/developer/workflow) | 分支、检查、PR |
| [WebUI 前端](/developer/webui) | Pallas-Bot-WebUI 联调与构建 |
| [官方插件 PyPI](/developer/extension-pypi-publish) | `pallas-plugin-*` / `pallas-core` 发版 |
| [WebUI API](/common/webui/api/) | 控制台 JSON API 分域 |

## 目录

| 区 | 内容 |
| --- | --- |
| [architecture/](/developer/architecture/overview) | 运行时、分层、分片、配置、治理 |
| [plugin-development/](/developer/plugin-development/first-plugin) | 首插件、骨架、元数据、配置、测试、发布 |
| [reference/](/developer/reference/repo-layout) | 仓库布局、API 分层、控制台约定 |
