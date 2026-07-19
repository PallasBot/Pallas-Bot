# 标准部署

面向 VPS / 本机长期运行。首次验证见 [快速开始](/guide/quickstart)。

相关：[Docker](/deploy/docker) · [配置](/deploy/config) · [连接 QQ](/guide/connect-qq) · [分片](/maintainer/deploy/sharded) · [FAQ](/deploy/faq)

## 部署前检查清单

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

## 步骤 1：获取源码

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
```

**验证**：目录内存在 `pyproject.toml`、`config/pallas.example.toml`。

**失败**：`git clone` 超时 → 配置代理或换镜像源后重试。

---

## 步骤 2：安装依赖

```bash
uv sync
```

可选：

```bash
uv sync --extra perf          # 分词加速
uv sync --extra deploy-shard  # 分片模板，另须配置 REDIS_URL
```

**验证**：退出码 `0`；`.venv` 已创建；`uv run python -c "import nonebot"` 无报错。

分片模板：`uv run python tools/apply_deploy_profile.py shard` → `pallas.toml [env]` 配置 `REDIS_URL` → `./scripts/run_sharded_bot.sh start`。消息审查 4.0 默认开启，WebUI「通用配置 → 消息审查」配置即可。分片 claim 依赖 Redis；`deploy-shard` 与 `coord-redis` 均安装 `redis` 客户端。

---

## 步骤 3：主配置 `config/pallas.toml`

```bash
cp config/pallas.example.toml config/pallas.toml
```

至少完成：

1. `[bootstrap] superusers` — 超管 QQ 号
2. `db_backend` — 新装 `postgresql`；3.x 升级可 `mongodb`
3. `[bootstrap.postgres]` 或 `[bootstrap.mongo]` — 与步骤 4 实际库一致

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

**验证**：`config/pallas.toml` 为文件（非目录）；`superusers`、数据库段已填写。勿提交含密钥的文件。

插件与通用项可在 Web 控制台修改（落盘 `data/pallas_config/webui.json`），见 [配置要点](/deploy/config)、[配置存储](/developer/architecture/config-storage)。

---

## 步骤 4：数据库

4.0 新装默认 PostgreSQL（`uv sync` 已含驱动）。3.x 升级、已有 Mongo 数据的站点可继续 MongoDB。

- PostgreSQL：[官方下载](https://www.postgresql.org/download/) · [deploy/pg/README.md](https://github.com/PallasBot/Pallas-Bot/blob/main/deploy/pg/README.md)
- MongoDB（升级沿用）：[Windows](https://www.runoob.com/mongodb/mongodb-window-install.html) · [Linux](https://www.runoob.com/mongodb/mongodb-linux-install.html)

库表由 Pallas-Bot 首次启动自动初始化（PG 须目标库已存在；应用账号不必为超级用户）。PG 排障见 [Docker 部署 · PG](/deploy/docker#pg-日志-fatal-database-pallasbot-does-not-exist)。

**验证**：

- PostgreSQL：`psql -h ... -U ... -d ...` 可登录，库名与 `pallas.toml` 中 `db` 一致
- MongoDB：`mongosh` 或客户端可连上配置的 host/port

---

## 步骤 5：语音资源（可选）

启动时自动下载语音包。

FFmpeg（唱歌等）：[安装 FFmpeg](https://napneko.github.io/config/advanced#%E5%AE%89%E8%A3%85-ffmpeg)

自动下载失败：手动解压 [Pallas.zip](https://huggingface.co/pallasbot/Pallas-Bot/blob/main/voices/Pallas.zip) 至 `resource/voices/`，结构见 [path_structure.txt](https://github.com/PallasBot/Pallas-Bot/blob/main/resource/voices/path_structure.txt)。

**验证**：启动日志无语音目录致命错误；`resource/voices/` 存在预期文件。

---

## 步骤 6：启动 Bot

```bash
uv run pallas
```

**验证**：

1. 日志显示 NoneBot / 插件加载完成，无数据库连接致命错误
2. 日志打印 Web 控制台初始口令（`data/pallas_console/`）
3. `http://<主机IP>:8088/pallas/api/health` 返回正常
4. `http://<主机IP>:8088/pallas/` 可用口令登录

未配置守护进程时，关闭终端即停止服务。Linux 生产环境使用下文 systemd 或 [Docker](/deploy/docker)。

---

## 步骤 7：接入 QQ 协议端

详见 [连接 QQ](/guide/connect-qq)。

**方式 A：协议端管理（推荐）**

1. 打开 `http://<主机IP>:8088/pallas/protocol`
2. 创建 NapCat 实例、扫码登录
3. WebSocket 指向 `ws://<Bot主机>:8088/onebot/v11/ws`

**方式 B：自管 NapCat**

按 [NapCat](https://napneko.github.io/) 安装，反向 WebSocket 填上述地址。

**验证**：控制台账号在线；群内 **牛牛帮助** 有响应。

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
ExecStart=/home/pallas/.local/bin/uv run pallas
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用：`sudo systemctl enable --now pallas-bot.service`。状态：`systemctl status pallas-bot`。

`tools/scripts/bot_watchdog.py` 探活 `/pallas/api/health`；Bot 已由 systemd 启动时须加 **`--no-spawn`**，避免重复占用端口。

### 备份与安全

- 备份：`data/pallas_config/webui.json`、`data/pallas_console/`、协议端实例数据
- 防火墙：仅对可信网络开放 `8088`
- 生产：勿长期开启 `pallas_webui_dev_mode`；公网访问须 HTTPS + 强口令
- 更新：`git pull` + `uv sync` + 重启；Docker 见 [Docker 部署](/deploy/docker)

定制仅改 `config/pallas.toml`、`data/`、`local/plugins/`。见 [升级与站点定制](/maintainer/deploy/upgrade)。

---

## 多进程分片（可选）

多只牛牛同机长跑且单进程卡顿时，使用 hub + worker，共用 `data/` 与同一份 `config/pallas.toml`。

- 启动：`./scripts/run_sharded_bot.sh start`（[分片架构](/maintainer/deploy/sharded)）
- Redis：**必需**；配置 `REDIS_URL` 并安装 `coord-redis` / `deploy-shard`
- 控制台与协议端管理仅访问 hub 端口（默认 `8088`）
- 切换前备份 `data/`；Docker 示例见 [Docker · 分片](/deploy/docker#多进程分片可选)

---

## 进程守护脚本（可选）

`tools/scripts/bot_watchdog.py`：请求 `/pallas/api/health`，连续失败后重启子进程或 Docker 容器。

| 场景 | 用法 |
| --- | --- |
| 由脚本拉起 Bot | `uv run python tools/scripts/bot_watchdog.py` |
| Bot 已由 systemd/Docker 运行 | 加 **`--no-spawn`** |
| 监护容器 | `--docker-container <名> --no-spawn` |

`HOST`/`PORT` 从环境变量或 `pallas.toml` `[bootstrap]` 读取。参数：`uv run python tools/scripts/bot_watchdog.py --help`。

---

## 访问地址

| 服务 | 默认地址 |
| --- | --- |
| Web 控制台 | `http://<主机>:8088/pallas/` |
| 协议端管理 | `http://<主机>:8088/pallas/protocol` |

自定义 `host`/`port` 或路径时，以 `pallas.toml` 与插件配置为准。

---

## AI 功能（可选）

基础功能（复读、轮盘等）不依赖独立 AI 服务。唱歌、闲聊、TTS 等须 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)，对 GPU/内存要求较高。

---

## 作为插件部署

面向已有 NoneBot 项目。独立部署本体时忽略本节。

1. 获取源码并 `uv sync`
2. 将 `src/foundation` 等内核层与所需 `src/plugins/*` 复制到现有 Bot
3. `bot.py` 启动时调用 `init_db()`、`ensure_voices()`（参见仓库 [`bot.py`](https://github.com/PallasBot/Pallas-Bot/blob/main/bot.py)）
4. 配置使用 `config/pallas.toml` + `webui.json`

插件列表：[插件索引](/plugins/index)。多 Bot 共存时注意 `matcher` 优先级与 `block` 插件。

---

## 相关文档

| 主题 | 文档 |
| --- | --- |
| 插件安装 | [安装插件](/guide/install-plugins) |
| 插件口令 | [插件索引](/plugins/index) |
| 控制台配置 | [Web 控制台](/common/webui) |
| 排障 | [FAQ](/deploy/faq) |
| Docker | [Docker 部署](/deploy/docker) |
