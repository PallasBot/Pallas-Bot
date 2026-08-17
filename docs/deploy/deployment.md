# 标准部署

完成本页后，你将在本机或 VPS 上从源码跑起 Pallas-Bot，并完成数据库、控制台与 QQ 接入。适合需要长期运行、可改代码或不用 Docker 的场景。首次只想快速验证时，可先看 [快速开始](/guide/quickstart)。

相关：[Docker](/deploy/docker) · [配置](/deploy/config) · [连接 QQ](/guide/connect-qq) · [分片](/maintainer/deploy/sharded) · [FAQ](/deploy/faq)

## 部署前准备

| 项 | 要求 |
| --- | --- |
| 硬件 | 建议 2 核 CPU / 4 GB 内存起；多 Bot 或 AI 须更高配置 |
| 系统 | Linux（推荐）或 Windows；长期运行优先 Linux + systemd |
| QQ 账号 | 协议端使用小号，勿用大号 |
| 网络 | 服务器可访问数据库端口；外网访问控制台须开放 HTTP 端口（默认 `8088`） |
| 数据库 | PostgreSQL（4.0 默认）；3.x 升级可沿用 MongoDB |
| 工具 | `git`、`Python 3.12+`（或由 `uv` 安装）、[`uv`](https://docs.astral.sh/uv/) |
| 配置 | `config/pallas.toml`（从示例复制，必做） |

多 Bot、高负载生产环境可选 [分片](/maintainer/deploy/sharded) 或 [Docker](/deploy/docker)。

---

## 1. 获取源码

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
```

目录内应有 `pyproject.toml` 与 `config/pallas.example.toml`。`git clone` 超时可配置代理或换镜像源后重试。

---

## 2. 安装依赖

```bash
uv sync
```

可选：

```bash
uv sync --extra perf          # 分词加速
uv sync --extra deploy-shard  # 分片模板，另须配置 REDIS_URL
```

退出码为 `0`、`.venv` 已创建，且 `uv run python -c "import nonebot"` 无报错时，依赖已就绪。

分片模板：`uv run python tools/apply_deploy_profile.py shard` → 在 `pallas.toml` 的 `[env]` 配置 `REDIS_URL` → `./scripts/run_sharded_bot.sh start`。消息审查 4.0 默认开启，在 WebUI「通用配置 → 消息审查」中调整即可。分片 claim 依赖 Redis；`deploy-shard` 与 `coord-redis` 均安装 `redis` 客户端。

单进程不需要 Redis；后台学习任务由数据库 outbox 和 `work aux` 消费。需要分片、本机 Embedding 或 Pallas-Bot-AI 队列时，可先执行 `uv run pallas redis start` 创建或复用共享 Redis。

### Python 依赖镜像源

`uv` 下载依赖较慢或无法连接 PyPI 时，可为单次命令指定兼容 PEP 503 的索引地址：

```bash
UV_DEFAULT_INDEX=https://<你的 Python 包索引>/simple uv sync
```

需要持续使用时，将 `UV_DEFAULT_INDEX` 写入当前用户的 shell 环境或 systemd 服务环境，再照常执行 `uv sync`、`uv run pallas ext install ...`。先用下面命令确认进程能读到配置：

```bash
UV_DEFAULT_INDEX=https://<你的 Python 包索引>/simple uv sync --dry-run
```

`UV_DEFAULT_INDEX` 是当前 uv 推荐的默认索引配置；`PIP_INDEX_URL` 只影响直接调用 pip 的场景。镜像站由用户自行选择并确认可信度、同步完整性和可用性，不建议把第三方地址提交到项目配置。

---

## 3. 写入主配置 `config/pallas.toml`

```bash
cp config/pallas.example.toml config/pallas.toml
```

至少完成：

1. `[bootstrap] superusers` — 超管 QQ 号
2. `db_backend` — 新装 `postgresql`；3.x 升级可 `mongodb`
3. `[bootstrap.postgres]` 或 `[bootstrap.mongo]` — 与下一步实际库一致

示例（PostgreSQL）：

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

从旧 `.env` 迁移：

```bash
uv run python tools/migrate_env_to_pallas.py
```

确认 `config/pallas.toml` 是文件（不是目录），且 `superusers` 与数据库段已填写。勿提交含密钥的文件。

插件与通用项可在 Web 控制台修改（落盘 `data/pallas_config/webui.json`），见 [配置要点](/deploy/config)、[配置存储](/developer/architecture/config-storage)。合并顺序为 `pallas.toml` → `.env` → `webui.json`。

---

## 4. 准备数据库

4.0 新装默认 PostgreSQL（`uv sync` 已含驱动）。3.x 升级、已有 Mongo 数据的站点可继续 MongoDB。

- PostgreSQL：[官方下载](https://www.postgresql.org/download/) · [deploy/pg/README.md](https://github.com/PallasBot/Pallas-Bot/blob/main/deploy/pg/README.md)
- MongoDB（升级沿用）：[Windows](https://www.runoob.com/mongodb/mongodb-window-install.html) · [Linux](https://www.runoob.com/mongodb/mongodb-linux-install.html)

库表由 Pallas-Bot 首次启动自动初始化（PG 须目标库已存在；应用账号不必为超级用户）。PG 排障见 [Docker 部署 · PG](/deploy/docker#排障)。

启动前确认：

- PostgreSQL：`psql` 可登录，库名与 `pallas.toml` 中 `db` 一致
- MongoDB：`mongosh` 或客户端可连上配置的 host/port

---

## 5. 语音资源（可选）

启动时会自动下载语音包。唱歌等能力还需要 [FFmpeg](https://napneko.github.io/config/advanced#%E5%AE%89%E8%A3%85-ffmpeg)。

自动下载失败时，手动解压 [Pallas.zip](https://huggingface.co/pallasbot/Pallas-Bot/blob/main/voices/Pallas.zip) 至 `resource/voices/`，结构见 [path_structure.txt](https://github.com/PallasBot/Pallas-Bot/blob/main/resource/voices/path_structure.txt)。

启动日志无语音目录致命错误，且 `resource/voices/` 有预期文件即可。

---

## 6. 启动 Bot

```bash
uv run pallas
```

启动成功时通常可见：

1. NoneBot / 插件加载完成，无数据库连接致命错误
2. 日志打印 Web 控制台初始密钥（`data/pallas_console/`）
3. `http://<主机IP>:8088/pallas/api/health` 返回正常
4. `http://<主机IP>:8088/pallas/` 可用密钥登录

启动后再执行 `uv run pallas status`，确认 `work 辅进程` 在运行；其日志在 `data/pallas_work/logs/work.log`。消息进程负责命令与实时回复，复读学习等持久化工作由该进程消费。

未配置守护进程时，关闭终端即停止服务。Linux 生产环境使用下文 systemd，或改用 [Docker](/deploy/docker)。

---

## 7. 接入 QQ 协议端

详见 [连接 QQ](/guide/connect-qq)。

**方式 A：协议端管理（推荐）**

1. 打开 `http://<主机IP>:8088/pallas/protocol`
2. 创建 NapCat 实例、扫码登录
3. WebSocket 指向 `ws://<Bot主机>:8088/onebot/v11/ws`

**方式 B：自管 NapCat**

按 [NapCat](https://napneko.github.io/) 安装，反向 WebSocket 填上述地址。

控制台账号在线，且群内 **牛牛帮助** 有响应时，接入完成。

---

## 生产环境

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

启用：`sudo systemctl enable --now pallas-bot.service`。状态：`systemctl status pallas-bot`。

`pallas daemon` 会探活 `/pallas/api/health`，连续失败后自动重启 unified Bot。它本身以前台进程运行，适合交给 systemd 管理；Bot 的业务日志仍写入 `data/bot/`。

### 备份与安全

- 备份：`data/pallas_config/webui.json`、`data/pallas_console/`、协议端实例数据
- 防火墙：仅对可信网络开放 `8088`
- 生产：勿长期开启 `pallas_webui_dev_mode`；公网访问须 HTTPS + 强密钥
- 更新：`git pull` + `uv sync` + 重启；Docker 见 [Docker 部署](/deploy/docker)

定制仅改 `config/pallas.toml`、`data/`、`local/plugins/`。见 [升级与站点定制](/maintainer/deploy/upgrade)。

---

## 多进程分片（可选）

多只牛牛同机长跑且单进程卡顿时，使用 hub + worker，共用 `data/` 与同一份 `config/pallas.toml`。

- 启动：`./scripts/run_sharded_bot.sh start`（[分片架构](/maintainer/deploy/sharded)）
- Redis：**必需**；配置 `REDIS_URL` 并安装 `coord-redis` / `deploy-shard`
- 控制台与协议端管理仅访问 hub 端口（默认 `8088`）
- 切换前备份 `data/`；Docker 示例见 [Docker · 分片](/deploy/docker)

---

## CLI 守护（可选）

`pallas daemon`：请求 `/pallas/api/health`，连续失败后重启 unified Bot。命令使用纯 Python 实现，Windows、macOS 和 Linux 均可运行。

```bash
uv run pallas daemon
```

默认每 15 秒探活，连续失败 3 次后重启。可用 `--interval`、`--timeout`、`--fail-threshold` 和 `--cooldown` 调整参数。该命令只守护 unified，分片部署请使用对应的 systemd/Docker 编排。

---

## 访问地址

| 服务 | 默认地址 |
| --- | --- |
| Web 控制台 | `http://<主机>:8088/pallas/` |
| 协议端管理 | `http://<主机>:8088/pallas/protocol` |

自定义 `host`/`port` 或路径时，以 `pallas.toml` 与插件配置为准。默认 WebUI 静态目录为 `data/pb_webui/public-react/`。

---

## AI 功能（可选）

基础功能（复读、轮盘等）不依赖独立 AI 服务。普通 LLM 对话在 Bot WebUI「AI 配置 → 接入」配置 Provider 即可；唱歌、TTS 和遗留 RWKV 才须 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)，并可能需要更高 GPU/内存配置。

---

## 作为插件部署

面向已有 NoneBot 项目。独立部署本体时忽略本节。

1. 获取源码并 `uv sync`
2. 将 `src/foundation` 等内核层与所需 `src/plugins/*` 复制到现有 Bot
3. `bot.py` 启动时调用 `init_db()`、`ensure_voices()`（参见仓库 [`bot.py`](https://github.com/PallasBot/Pallas-Bot/blob/main/bot.py)）
4. 配置使用 `config/pallas.toml` + `webui.json`

插件列表：[插件索引](/plugins/)。多 Bot 共存时注意 `matcher` 优先级与 `block` 插件。

---

## 相关文档

| 主题 | 文档 |
| --- | --- |
| 插件安装 | [安装插件](/guide/install-plugins) |
| 插件命令 | [插件索引](/plugins/) |
| 控制台配置 | [Web 控制台](/common/webui) |
| 排障 | [FAQ](/deploy/faq) |
| Docker | [Docker 部署](/deploy/docker) |
