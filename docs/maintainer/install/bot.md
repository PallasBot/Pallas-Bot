# 本体安装

> 目标：安装 Pallas-Bot 本体并完成首次启动
> 准备：按所选部署方式满足前置条件（见下方表格）
> 完成之后：Bot 可运行，控制台可访问；后续接协议端即可连 QQ

本页是各部署方式的入口。按场景选择下方文档即可，不必把所有页面读完。

## 前置条件

| 项 | 要求 |
| --- | --- |
| Python | 3.12 |
| 包管理 | `uv` |
| 数据库 | PostgreSQL（V4 默认）；3.x 升级可沿用 MongoDB，见 [配置参考](/maintainer/reference/config) |
| Redis | 仅分片、AI 等场景需要 |

## 按场景选择入口

| 场景 | 文档 |
| --- | --- |
| 快速跑通 | [快速开始](/guide/quickstart) |
| 非 Docker 长期部署 | [Release 部署包](#release-部署包推荐) |
| 容器部署 | [Docker 部署](/maintainer/deploy/docker) |
| 修改本体源码 | [源码安装](/guide/install-source) |
| 插件与扩展 | [安装插件](/guide/install-plugins) · [AI 扩展](/guide/ai) |
| 本地开发 | [开发环境](/developer/environment) |

## Release 部署包（推荐）

不使用 Docker、也不准备修改 Bot 本体时，从 [GitHub Releases](https://github.com/PallasBot/Pallas-Bot/releases/latest) 下载当前版本的 `pallas-bot-<version>.tar.gz`：

```bash
tar -xzf pallas-bot-<version>.tar.gz
cd pallas-bot-<version>
uv sync --extra perf
cp config/pallas.example.toml config/pallas.toml
# 编辑 config/pallas.toml 的 [bootstrap]、superusers 与数据库连接
uv run pallas
```

部署包已经包含对应版本的 WebUI，以及用于后续 Release 更新的浅层 Git 元数据；**不需要执行 `git init`**。`config/pallas.toml`、`data/` 与 `local/plugins/` 不进入版本控制，更新时会保留。

Bot 本体和 WebUI 使用独立的更新开关。需要更新时见[更新 Pallas-Bot](/guide/update)。需要自行修改内核、运行测试或提交 PR 时，再使用[源码安装](/guide/install-source)。

## V4 本体职责

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
