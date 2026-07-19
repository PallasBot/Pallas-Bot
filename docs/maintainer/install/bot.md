# 本体安装

安装 Pallas-Bot 本体并完成首次启动。

## 前置条件

| 项 | 要求 |
| --- | --- |
| Python | 3.12 |
| 包管理 | `uv` |
| 数据库 | PostgreSQL（4.0 默认）；3.x 升级可沿用 MongoDB，见 [配置参考](/maintainer/reference/config) |
| Redis | 仅分片、AI 等场景需要 |

## 安装入口

| 场景 | 文档 |
| --- | --- |
| 快速跑通 | [快速开始](/guide/quickstart) |
| 插件与扩展 | [安装插件](/guide/install-plugins) · [AI 扩展](/guide/ai) |
| 本地开发 | [开发环境](/developer/environment) |

## 4.0 本体职责

- 消息入口
- 插件加载
- 配置合并
- WebUI API
- 分片协调
- AI callback 落地

决斗、MAA 等由官方插件提供，见 [安装官方插件](official-extensions.md)。
