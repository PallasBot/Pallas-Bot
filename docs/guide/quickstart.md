# 快速开始

这一页带你完成第一次启动：打开网页控制台，并为连接 QQ 做好准备。Bot 启动后还需要 [连接 QQ](connect-qq.md)，它才能在群里收发消息。

## 开始前准备

| 需要准备 | 用途 |
| --- | --- |
| 一台能长期运行的电脑或服务器 | 运行 Bot 和网页控制台 |
| 一个用于机器人的 QQ 账号 | 连接协议端后收发群消息 |
| Release 部署包、源码环境或 Docker | 按使用场景安装 Bot |

PostgreSQL 是默认数据库。Docker 部署会一并启动它；源码部署可以使用本机数据库，也可以用 Docker 单独启动。

LLM、唱歌和画图都不是首次启动的前置条件。先让 Bot 正常上线，之后再按需安装插件或配置 AI。

## 第 1 步：选择部署方式

| 你的情况 | 推荐方式 | 完成后你会得到 |
| --- | --- | --- |
| 想直接部署到服务器，不准备修改代码 | [Docker 部署](/deploy/docker) | Bot、数据库和控制台容器 |
| 不使用 Docker，也不准备修改代码 | [Release 部署包](/maintainer/install/bot#release-部署包推荐) | 已包含 WebUI、可自动更新的精简 Bot 目录 |
| 要开发、调试或修改主仓代码 | [源码安装](install-source.md) | 本地 Python 环境和可运行的 Bot |

::: tip 新手推荐
没有源码开发需求时，优先选择 Docker；不使用 Docker 时选择 Release 部署包。只有需要修改本体或参与开发时才 clone 源码仓库。
:::

::: tip 下载慢或失败
先看报错来自哪里：拉容器镜像或构建基础镜像，见 [Docker 下载慢与镜像源](/deploy/docker#下载慢与镜像源)；`uv sync` 下载 Python 依赖失败，见 [Python 依赖镜像源](/deploy/deployment#python-依赖镜像源)。控制台自带的 Git 镜像源只用于 GitHub 资源，不能替代这两类配置。
:::

按所选文档完成安装、填写 `superusers` 与数据库配置，然后启动 Bot。

## 第 2 步：确认 Bot 已启动

启动成功后，先检查下面三件事：

1. 终端日志没有持续出现数据库连接失败。
2. 日志中出现网页控制台的初始密码。
3. 浏览器能打开 `http://<主机>:8088/pallas/`。

本机运行时，`<主机>` 填 `127.0.0.1`。部署在服务器上时，换成服务器 IP 或域名，并确认防火墙已放行 8088。

首次只看到控制台、还没有 QQ 消息是正常的：这说明 Bot 本体已经运行，但协议端尚未连接。

## 持久化部署

临时运行可以直接使用 `uv run pallas`；需要关闭终端后仍保持运行时，使用 CLI 守护：

```bash
uv run pallas daemon
```

它会启动 unified Bot，定时探活控制台，连续失败后自动重启。Windows、macOS 和 Linux 都可以使用。Linux 服务器建议交给 systemd：

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

## 第 3 步：连接 QQ 并完成验收

打开 [连接 QQ](connect-qq.md)，在协议端管理页新建 NapCat 实例并扫码登录。

协议端显示“在线”后，把机器人拉进测试群并发送：

```text
牛牛帮助
```

能收到帮助图，表示 Bot、协议端和群消息链路已经正常工作。

## 接下来做什么

- 为每只机器人配置 [号主](bot-owner.md)，启用号主向管理能力。
- 在 [网页控制台](web-console.md) 查看实例、日志和插件状态。
- 按需 [安装插件](install-plugins.md)，或配置 [聊天、媒体与 AI Runtime](ai-runtime-choice.md)。
- 日常配置与保存规则见 [配置从哪改](config.md)。
- 已有实例升级、控制台一键更新与自动更新见 [更新 Pallas-Bot](update.md)。
