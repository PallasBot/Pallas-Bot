# 快速开始

> **目标**：完成 Pallas-Bot 的第一次启动，打开网页控制台并为连接 QQ 做好准备  
> **完成之后**：控制台可访问、Bot 在后台运行，只差连接 QQ（见 [连接 QQ](connect-qq.md)）

## 开始前准备

- **一台能长期运行的电脑或服务器**：运行 Bot 和网页控制台。
- **一个 Bot 使用的 QQ 账号**：连接协议端后收发群消息。
- **一种部署方式**：Docker、Release 部署包或源码安装。

PostgreSQL 是默认数据库。Docker 部署会一并启动它；源码部署可以使用本机数据库，也可以用 Docker 单独启动。

Release 或源码路径先完成 [环境准备](prepare-environment.md)。本页的目标就是让 Bot 正常上线；完成下列步骤后，可按需添加玩法与 AI 能力。

## 第 1 步：选择部署方式

- **[Docker 部署](/maintainer/deploy/docker)**：适合 Windows、macOS、Linux；Docker Desktop 或 Docker Engine 会同时启动 Bot、PostgreSQL 和控制台。没有源码开发需求时优先选此路径。
- **[Release 部署包](/maintainer/install/bot)**：适合 Windows、macOS、Linux；准备 Python 3.12、`uv` 和 PostgreSQL，得到包含 WebUI、可更新的精简部署目录。
- **[源码安装](install-source.md)**：适合修改代码、调试或参与开发；准备 Git、Python 3.12、`uv` 和 PostgreSQL。

::: tip 新手推荐
没有源码开发需求时，优先选择 Docker；不使用 Docker 时选择 Release 部署包。只有需要修改本体或参与开发时才 clone 源码仓库。
:::

::: tip 下载慢或失败
先看报错来自哪里：拉容器镜像或构建基础镜像，见 [Docker 下载慢与镜像源](/maintainer/deploy/docker#下载慢与镜像源)；`uv sync` 下载 Python 依赖失败，见 [Python 依赖镜像源](prepare-environment.md#python-依赖镜像源)。控制台自带的 Git 镜像源只用于 GitHub 资源，不能替代这两类配置。
:::

按所选文档完成安装、填写 `superusers` 与数据库配置，然后启动 Bot。

## 第 2 步：确认 Bot 已启动

启动成功后，先检查下面三件事：

1. 终端日志没有持续出现数据库连接失败。
2. 日志中出现网页控制台的初始密码。
3. 浏览器能打开 `http://<主机>:8088/pallas/`。

日志位置因部署方式而异：Docker 用 `docker compose logs pallasbot`，源码部署默认在 `data/` 下。本机运行时，`<主机>` 填 `127.0.0.1`。部署在服务器上时，换成服务器 IP 或域名，并确认防火墙已放行 8088。

首次只看到控制台、还没有 QQ 消息是正常的：这说明 Bot 本体已经运行，但协议端尚未连接。

::: details 进阶：让 Bot 在关闭终端后仍保持运行
临时运行直接使用 `uv run pallas` 即可；需要守护时使用 CLI：

```bash
uv run pallas daemon
```

它会启动 unified Bot，定时探活控制台，连续失败后自动重启。Windows、macOS 和 Linux 都可以使用。Linux 服务器可交给 systemd：

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

systemd 日志用于查看守护进程状态；Bot 业务日志仍按自身配置写入 `data/bot/`，控制台也可以查看日志。
:::

## 第 3 步：连接 QQ 并完成验收

按 [连接 QQ](connect-qq.md) 的指引，在协议端管理页（`http://<主机>:8088/pallas/protocol`）新建 NapCat 实例并扫码登录。

协议端显示“在线”后，把 Bot 拉进测试群并发送：

```text
牛牛帮助
```

能收到帮助图，表示 Bot、协议端和群消息链路已经正常工作。

::: details 进阶：上线前核对

- [ ] 已按本页、[Release 部署包安装](/maintainer/install/bot)、[源码安装](install-source.md) 或 [Docker 部署](/maintainer/deploy/docker) 跑通 Bot。
- [ ] `config/pallas.toml` 已填写 `superusers` 与数据库连接。
- [ ] 数据库可连接；启动日志没有持续致命错误。
- [ ] 网页控制台可登录，协议端账号显示在线。
- [ ] 已为该牛配置 [号主](bot-owner.md)，测试群能收到 `牛牛帮助`。

生产与进阶设置见：

- [标准生产部署](/maintainer/deploy/deployment)：systemd、备份与防火墙。
- [Docker 部署](/maintainer/deploy/docker)：Compose 运行方式。
- [配置要点](/maintainer/reference/config-production)：生产配置检查。
- [分片部署](/maintainer/deploy/sharded)：多牛分片。
:::

## 接下来做什么

- 为每只牛牛配置 [号主](bot-owner.md)，启用号主向管理能力。
- 在 [网页控制台](web-console.md) 查看实例、日志和插件状态。
- 按需 [安装插件](install-plugins.md)，或配置 [聊天、媒体与 AI Runtime](ai-runtime-choice.md)。
- 日常配置与保存规则见 [配置从哪改](config.md)。
- 已有实例升级、控制台一键更新与自动更新见 [更新 Pallas-Bot](update.md)。
