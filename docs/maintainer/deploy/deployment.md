# 标准生产部署

> **目标**：让已完成首次安装的 Pallas-Bot 长期稳定运行  
> **完成之后**：进程由守护服务管理，备份、安全与扩展路径明确

本页面向 Release 部署包或源码目录的生产环境。Docker 用户直接使用 [Docker 部署](/maintainer/deploy/docker)，其中已包含 Compose 运行与数据库管理。

## 1. 先完成首次安装

以下任一路径完成后，控制台应已可访问：

- [Release 部署包安装](/maintainer/install/bot)：不使用 Docker，也不修改本体代码。
- [源码安装](/guide/install-source)：修改代码、调试或参与开发。
- [Docker 部署](/maintainer/deploy/docker)：Compose 同时管理 Bot、PostgreSQL 和控制台。

首次安装后，按 [连接 QQ](/guide/connect-qq) 接入协议端。测试群收到 `牛牛帮助` 后，再继续本页的生产加固。

## 2. 运行环境

- **系统**：长期运行优先 Linux；Windows、macOS 也可运行 Bot 与 CLI 守护。
- **资源**：建议 2 核 CPU、4 GB 内存起；多 Bot、分片或 AI 媒体需要更高资源。
- **网络**：Bot 需要访问数据库；外网访问控制台时开放应用端口（默认 `8088`）。
- **账号**：协议端使用机器人小号，不使用日常主账号。

Python、`uv` 与 PostgreSQL 的跨平台准备见 [环境准备](/guide/prepare-environment)。生产配置检查见 [配置要点](/maintainer/reference/config-production)。

## 3. 持续运行

### CLI 守护

`pallas daemon` 定时探活 `/pallas/api/health`，连续失败后重启 unified Bot：

```bash
uv run pallas daemon
```

该命令可运行在 Windows、macOS 和 Linux。生产环境仍应交给系统守护服务管理：Windows 使用任务计划程序，macOS 使用 `launchd`，Linux 使用 systemd。

### systemd（Linux）

```ini
[Unit]
Description=Pallas-Bot
After=network.target postgresql.service

[Service]
Type=simple
User=pallas
WorkingDirectory=/opt/Pallas-Bot
ExecStart=/home/pallas/.local/bin/uv run pallas daemon
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

保存为 `/etc/systemd/system/pallas-bot.service` 后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pallas-bot
sudo journalctl -u pallas-bot -f
```

## 4. 备份与安全

- 定期备份 `config/pallas.toml`、`data/pallas_config/webui.json`、`data/pallas_console/` 与整个 `data/`。
- 仅对可信网络开放控制台端口；公网访问使用 HTTPS 与强密钥。
- 生产环境不要长期开启 `pallas_webui_dev_mode`。
- 站点定制只放在 `config/pallas.toml`、`data/` 和 `local/plugins/`，更新策略见 [升级与站点定制](/maintainer/deploy/upgrade)。

## 5. 按规模扩展

- **分片**：多机部署、账号隔离或高可用时，使用 [分片部署](/maintainer/deploy/sharded)。Redis 是分片协调事实源。
- **AI 媒体**：普通 LLM 聊天在 **AI 配置 → 接入** 配 Provider；唱歌、TTS 和遗留 RWKV 见 [AI Runtime](/maintainer/install/ai-runtime)。
- **官方插件**：用户安装见 [安装插件](/guide/install-plugins)；精简镜像、分片与回滚见 [官方插件运维](/maintainer/install/official-extensions)。

## 常用地址

- 网页控制台：`http://<主机>:8088/pallas/`
- 协议端管理：`http://<主机>:8088/pallas/protocol`

自定义 `host`、`port` 或路径时，以 `config/pallas.toml` 与插件配置为准。

## 上线验收与相关阅读

- [快速开始](/guide/quickstart)：包含上线前核对清单。
- [安装验收 Checklist](/maintainer/install/ga-install-checklist)：多路径详细走查。
- [日志](/maintainer/operate/logs) 与 [排障](/maintainer/operate/troubleshooting)。
- [配置参考](/maintainer/reference/config) 与 [配置要点](/maintainer/reference/config-production)。
