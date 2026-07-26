# 本体安装

本页说明安装 Pallas-Bot 本体并完成首次启动所需的前提与入口。按场景选择下方文档即可，不必把所有页面读完。

## 前置条件

| 项 | 要求 |
| --- | --- |
| Python | 3.12 |
| 包管理 | `uv` |
| 数据库 | PostgreSQL（4.0 默认）；3.x 升级可沿用 MongoDB，见 [配置参考](/maintainer/reference/config) |
| Redis | 仅分片、AI 等场景需要 |

## 按场景选择入口

| 场景 | 文档 |
| --- | --- |
| 快速跑通 | [快速开始](/guide/quickstart) |
| 源码长期部署 | [标准部署](/deploy/deployment) |
| 容器部署 | [Docker 部署](/deploy/docker) |
| 插件与扩展 | [安装插件](/guide/install-plugins) · [AI 扩展](/guide/ai) |
| 本地开发 | [开发环境](/developer/environment) |

## 4.0 本体职责

本体负责：

- 消息入口
- 插件加载
- 配置合并（`pallas.toml` → `.env` → `webui.json`）
- WebUI API 与默认静态目录 `data/pb_webui/public-react/`
- 分片协调
- 媒体 / RWKV callback 落地

决斗、MAA 等由官方插件提供，见 [安装官方插件](official-extensions.md)。

## 下一步

1. 按所选入口完成安装与启动。
2. 接入协议端：[协议端](protocol.md) 或 [连接 QQ](/guide/connect-qq)。
3. 上线前走查：[安装验收 Checklist](ga-install-checklist.md)。
