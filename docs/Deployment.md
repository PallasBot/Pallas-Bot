# Pallas-Bot 3.0 部署教程

> 导航：[`README`](../README.md) · [`Docker 部署`](DockerDeployment.md) · [`配置要点`](Config.md) · [`多进程分片`](architecture/bot_process_sharding.md) · [`3.0 迁移`](Migration-v3.md) · [`FAQ`](FAQ.md)

本文面向**本机或 VPS 上的生产/长期运行**部署：按步骤完成环境、配置与协议端接入，并在每步说明如何确认成功。

## 部署前检查清单

在开始前请确认：

| 项 | 要求 |
| --- | --- |
| 硬件 | 建议 **2 核 CPU / 4 GB 内存** 起；多牛或启用 AI 功能需更高配置 |
| 系统 | Linux（推荐）或 Windows；长期运行优先 Linux + systemd |
| QQ 账号 | 使用**小号**登录协议端，勿用大号 |
| 网络 | 服务器可访问数据库端口；若外网访问控制台，需开放 **HTTP 端口**（默认 `8088`） |
| 数据库 | 已安装 **MongoDB** 或 **PostgreSQL**，或可连接远程实例 |
| 工具 | `git`、`Python 3.12+`（或由 `uv` 自动安装）、[`uv`](https://docs.astral.sh/uv/) |
| 配置 | 将准备 **`config/pallas.toml`**（从示例复制，**非可选项**） |

> 多牛、高负载生产环境可选用 [多进程分片](architecture/bot_process_sharding.md) 或 [Docker 部署](DockerDeployment.md)。

---

## 步骤 1：获取源码

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
```

**如何确认成功**：目录内存在 `pyproject.toml`、`config/pallas.example.toml`。

国内网络若 `git clone` 失败，可配置代理或换镜像源后重试。

---

## 步骤 2：安装依赖

```bash
uv sync
```

若 `pallas.toml` 中计划使用 PostgreSQL：

```bash
uv sync --extra pg
```

消息量较大、希望加速分词时（可选）：

```bash
uv sync --extra perf
```

**如何确认成功**：命令退出码为 `0`，且 `.venv` 已创建；可执行 `uv run python -c "import nonebot"` 无报错。

### 可选部署模板

除默认单进程外，可选用 [deploy/](deploy/README.md) 中的模板（**不默认启用**）：

| 场景 | 依赖 | 应用配置 |
| --- | --- | --- |
| 多进程分片 | `uv sync --extra deploy-shard` | `uv run python tools/apply_deploy_profile.py shard` → 在 `pallas.toml [env]` 配置 `REDIS_URL` → `./scripts/run_sharded_bot.sh start` |
| 消息审查 | `uv sync --extra message-scrub` | `uv run python tools/apply_deploy_profile.py message-scrub` |

当前分片模式**依赖 Redis 协调 claim**。`deploy-shard` 与 `coord-redis` 均安装 `redis` 依赖；`shard` extra 不含 redis 客户端，不能单独满足当前分片运行要求。

---

## 步骤 3：准备主配置 `config/pallas.toml`（必做）

```bash
cp config/pallas.example.toml config/pallas.toml
```

编辑 **`config/pallas.toml`**，至少完成：

1. **`[bootstrap] superusers`**：填写你的 QQ 号（超管，用于控制台与高危操作）。
2. **`db_backend`**：设为 `mongodb` 或 `postgresql`。
3. **`[bootstrap.mongo]`** 或 **`[bootstrap.postgres]`**：填写数据库地址、库名、账号密码（与步骤 4 中实际库一致）。

示例（MongoDB）：

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "mongodb"

[bootstrap.mongo]
host = "127.0.0.1"
port = 27017
db = "PallasBot"
```

从旧版 `.env` 迁移：

```bash
uv run python tools/migrate_env_to_pallas.py
```

**如何确认成功**：`config/pallas.toml` 为**文件**（非目录），且 `superusers`、数据库段已填写。勿将含密钥的文件提交到 git。

插件与通用项可在首次启动后于 Web 控制台修改（落盘 `data/pallas_config/webui.json`），详见 [配置要点](Config.md) 与 [配置存储](architecture/settings-storage.md)。

---

## 步骤 4：准备数据库

任选 **MongoDB** 或 **PostgreSQL**，保证 Bot 所在机器能连通。

- MongoDB：[Windows 安装](https://www.runoob.com/mongodb/mongodb-window-install.html) · [Linux 安装](https://www.runoob.com/mongodb/mongodb-linux-install.html)
- PostgreSQL：[官方下载](https://www.postgresql.org/download/) · 使用 PG 时需已执行 `uv sync --extra pg`

库表由 Pallas-Bot **首次启动时自动初始化**，无需手工建表（PG 需库已存在，见 [Docker 部署 · PG 排障](DockerDeployment.md#pg-日志-fatal-database-pallasbot-does-not-exist)）。

**如何确认成功**：

- MongoDB：`mongosh` 或客户端能连上 `pallas.toml` 中的 host/port。
- PostgreSQL：`psql -h ... -U ... -d ...` 可登录，且库名与 `pallas.toml` 中 `db` 一致。

---

## 步骤 5：（可选）语音资源

Pallas-Bot 启动时会尝试自动下载语音包。若需 FFmpeg（唱歌等）：

- [安装 FFmpeg](https://napneko.github.io/config/advanced#%E5%AE%89%E8%A3%85-ffmpeg)

自动下载失败时，可手动将 [Pallas.zip](https://huggingface.co/pallasbot/Pallas-Bot/blob/main/voices/Pallas.zip) 解压到 `resource/voices/`，结构见 [path_structure.txt](../resource/voices/path_structure.txt)。

**如何确认成功**：启动日志无语音目录相关致命错误；`resource/voices/` 下存在预期文件。

---

## 步骤 6：启动 Bot

```bash
uv run nb run
```

**如何确认成功**：

1. 日志中出现 NoneBot / 插件加载完成，无数据库连接致命错误。
2. 日志中打印 **Web 控制台初始口令**（存于 `data/pallas_console/`）。
3. 浏览器访问 `http://<主机IP>:8088/pallas/api/health`（或控制台首页），返回正常。
4. 浏览器打开 `http://<主机IP>:8088/pallas/`，使用口令登录成功。

> **勿关闭运行 Bot 的终端**（未配置守护时关闭即停止服务）。Linux 生产环境请使用下文 **systemd** 或 [Docker](DockerDeployment.md)。

---

## 步骤 7：接入 QQ 协议端

**方式 A：协议端管理（推荐）**

1. 打开 `http://<主机IP>:8088/protocol/console/`（端口以 `pallas.toml` 为准）。
2. 使用与控制台相同的登录方式鉴权。
3. 在页面内创建 NapCat 实例、登录 QQ、确认 OneBot WebSocket 已指向 Bot（通常为 `ws://<Bot主机>:8088/onebot/v11/ws`）。

详见 [`pallas_protocol` 插件说明](plugins/pallas_protocol/README.md)。

**方式 B：自管 NapCat / 其他 OneBot 客户端**

- 按 [NapCat](https://napneko.github.io/) 等官方文档安装。
- 在协议端新建 **WebSocket 客户端**，URL：`ws://<Bot主机>:8088/onebot/v11/ws`（远程部署时将 `localhost` 换为 Bot 机器 IP）。

**如何确认成功**：

1. 控制台 **「在线 Bot」** 或协议端页显示账号已连接。
2. 在 QQ 群 @ 牛牛或发送测试指令有正常回复。

---

## 生产环境建议

### 使用 systemd 守护（Linux）

示例 unit（路径与用户按实际修改）：

```ini
[Unit]
Description=Pallas-Bot
After=network.target mongod.service

[Service]
Type=simple
User=pallas
WorkingDirectory=/opt/Pallas-Bot
ExecStart=/home/pallas/.local/bin/uv run nb run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用：`sudo systemctl enable --now pallas-bot.service`。状态：`systemctl status pallas-bot`。

也可使用仓库 **`tools/scripts/bot_watchdog.py`** 探活 `/pallas/api/health`；若 Bot 已由 systemd 启动，须加 **`--no-spawn`**，避免重复占用端口。详见 [进程守护脚本](#进程守护脚本可选)。

### 备份 `data/` 目录

以下内容建议**定期备份**（停机或快照均可）：

- `data/pallas_config/webui.json` — WebUI 配置
- `data/pallas_console/` — 控制台口令哈希
- `data/` 下协议端实例、注册表等（分片/多牛共用同一 `data/`）

配置模板 `config/pallas.toml` 请单独版本管理或加密备份，勿与镜像混放密钥。

### 防火墙与安全

- 仅对**可信网络**开放 `8088`（控制台、协议端管理、OneBot HTTP/WS）。
- 生产环境**不要**开启 `pallas_webui_dev_mode`。
- 若必须公网访问控制台，请配合反向代理、HTTPS 与强口令；`ACCESS_TOKEN` 见 [配置要点](Config.md)。

### 更新

- **git 部署**：`git pull origin main --autostash` 后 `uv sync`（依赖变更时）并重启进程。
- **Docker**：见 [Docker 部署 · 后续更新](DockerDeployment.md#后续更新)。
- 控制台 **「版本与更新」** 可更新 Web 静态资源；git 工作副本内可在线拉主仓（Docker 纯镜像树除外）。**任何代码/依赖更新后须重启 Bot。**

自定义请尽量只改 **`config/pallas.toml`**、**`data/`**、**`local/plugins/`**，避免直接改 `src/` 跟踪文件。见 [站点定制与更新](architecture/site-customization-and-updates.md)。

---

## 多进程分片（可选）

同一台机器长期运行**多只牛牛**且单进程卡顿时，可使用 **hub + worker**，共用 **`data/`** 与同一份 **`config/pallas.toml`**。

- 启动：`./scripts/run_sharded_bot.sh start`（详见 [多进程分片架构说明](architecture/bot_process_sharding.md)）。
- Redis：**必需**；请先配置 `REDIS_URL` 并安装 `coord-redis` / `deploy-shard`，否则分片 claim 无法正常工作。
- 控制台与协议端管理仅访问 **hub** 端口（默认 `8088`）。
- 切换前请备份 `data/`；Docker 示例见 [Docker 部署 · 多进程分片](DockerDeployment.md#多进程分片可选)。

---

## 进程守护脚本（可选）

仓库提供 **`tools/scripts/bot_watchdog.py`**：请求 **`/pallas/api/health`**，连续失败后结束子进程并重启，或对 Docker 容器执行 `docker restart`。

| 场景 | 用法 |
| --- | --- |
| 由脚本拉起 Bot | `uv run python tools/scripts/bot_watchdog.py` |
| Bot 已由 systemd/Docker 运行 | 必须加 **`--no-spawn`** |
| 监护容器 | `--docker-container <名> --no-spawn` |

`HOST`/`PORT` 从环境变量或 `config/pallas.toml` 的 `[bootstrap]` 读取。完整参数：`uv run python tools/scripts/bot_watchdog.py --help`。

---

## 访问控制台与协议端

| 服务 | 默认地址 |
| --- | --- |
| Web 控制台 | `http://<主机>:8088/pallas/` |
| 协议端管理 | `http://<主机>:8088/protocol/console/` |

修改了 `host`/`port` 或自定义路径时，以 `pallas.toml` 与插件配置为准。

---

## AI 功能（可选）

基础功能（复读、轮盘等）不依赖独立 AI 服务。唱歌、酒后闲聊、TTS 等需 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)，对 GPU/内存要求较高，性能不足可跳过。

---

## 作为插件部署

> 面向已有 NoneBot 项目的开发者；仅部署独立牛牛可跳过本节。

1. 获取源码并 `uv sync`（PG 用 `--extra pg`）。
2. 将 `src/foundation` 等内核层与所需 `src/plugins/*` 复制到现有 Bot。
3. 在 `bot.py` 中于启动时调用 `init_db()`、`ensure_voices()`（参见仓库 [`bot.py`](../bot.py)）。
4. 配置使用 **`config/pallas.toml`** + **`webui.json`**。

插件列表见 [插件索引](plugins/README.md)。多 Bot 共存时注意 `matcher` 优先级与 `block` 插件。

---

## 社区与支持

与 [README 社区区块](../README.md#qq-群) 保持一致。

### 开发者

- [`牛牛听话!`](https://qm.qq.com/q/yIiAajYwms)

### 拉牛牛

- [`西海福牛养殖基地`](https://qm.qq.com/q/5GjZ2xHeb6)
- [`牛牛工坊`](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=snSe5PkcmHZrD0OA5Wzl2RAnM-qoAMUc&authKey=T%2FQlcyy31oE7YyMDMd7Yys7utl5a9jP84VYgnknra8Knsq3BhEy5TrwiWK7rG8j6&noverify=0&group_code=1043301356)

### 闲聊

- [`西海福牛养殖学院`](https://qm.qq.com/q/8P)
- [`丽丽玛玛玛?`](https://qm.qq.com/q/Qgc6ir7Jk)
