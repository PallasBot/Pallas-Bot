# Pallas-Bot Docker 部署

使用 **Docker Compose** 运行官方镜像，适合生产环境统一版本、隔离依赖。需预先安装 [Docker](https://docs.docker.com/get-docker/) 与 Compose 插件（`docker compose version` 有输出即可）。

::: tip 导航
[README](../README.md) · [标准部署](Deployment.md) · [配置要点](Config.md) · [连接 QQ](guide/connect-qq.md) · [多进程分片](architecture/bot_process_sharding.md) · [FAQ](FAQ.md)
:::

## 部署前检查清单

| 项 | 说明 |
| --- | --- |
| Docker | Engine + Compose V2；Linux 可用 `curl -fsSL https://get.docker.com \| bash` |
| 目录 | 单独目录存放 `docker-compose.yml` 与 `pallas-bot/` 数据（勿用中文空名目录作项目名，见排障） |
| 配置 | **`pallas-bot/config/pallas.toml`** 必须从示例复制并编辑（**文件**，非目录） |
| 数据库 | 选定 MongoDB（默认栈）或 PostgreSQL（`--profile postgres`） |
| 端口 | 宿主机映射 `8088`（或自定义）需在防火墙放行 |
| 备份 | 持久化 **`pallas-bot/data`** 与数据库卷 |

---

## 步骤 1：安装 Docker 与 Compose

- [Windows Docker Desktop](https://docs.docker.com/desktop/install/windows-install/)（推荐 WSL2 后端）
- [Linux 安装](https://docs.docker.com/engine/install/ubuntu/)

验证：

```bash
docker --version
docker compose version
```

**如何确认成功**：两条命令均正常输出版本号。

::: details Linux Rootless（可选）
`dockerd-rootless-setuptool.sh install`，见 [官方文档](https://docs.docker.com/engine/security/rootless/)。
:::

---

## 步骤 2：准备 Compose 与目录

1. 将仓库 [`docker-compose.yml`](../docker-compose.yml) 复制到部署目录（例如 `~/pallas-deploy/`）。

2. 创建数据目录并复制主配置：

```bash
mkdir -p pallas-bot/config pallas-bot/data
cp /path/to/Pallas-Bot/config/pallas.example.toml pallas-bot/config/pallas.toml
```

3. 编辑 **`pallas-bot/config/pallas.toml`**（必做）：`superusers`、`db_backend`、数据库段。

4. 按需调整 compose 中 **`volumes`**：

```yml
volumes:
  - ./pallas-bot/resource/voices:/app/resource/voices
  - ./pallas-bot/config/pallas.toml:/app/config/pallas.toml
  - ./pallas-bot/data:/app/data
```

要点：

- **`pallas.toml` 必须是宿主机上的普通文件**；若误建成文件夹，启动会报 `not a directory`（见排障）。
- **只挂载 `resource/voices`**，勿把整个 `resource` 挂到 `/app/resource`，否则会盖住镜像内 `styles/default`。
- **`data`** 持久化 WebUI、协议端、控制台口令等。

**如何确认成功**：`file pallas-bot/config/pallas.toml` 显示为文本文件；`pallas-bot/data` 目录存在。

---

## 步骤 3：选择数据库并启动

::: details MongoDB（默认栈）
`pallas.toml` 中 `db_backend = "mongodb"`（或省略默认）。compose 已为 Bot 注入 `MONGO_HOST=mongodb`。

```bash
docker compose up -d
```
:::

::: details PostgreSQL（内置 compose 数据库）
1. `pallas.toml` 设 `db_backend = "postgresql"` 并填写 `[bootstrap.postgres]`。
2. 复制 [`config/compose.env.example`](../config/compose.env.example) → **`pallas-bot/config/compose.env`**，使 **`PG_*`** 与 TOML 一致。
3. 启动：

```bash
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres up -d
```
:::

**如何确认成功**：

```bash
docker compose ps
docker compose logs -f pallasbot
curl -s http://127.0.0.1:8088/pallas/api/health
```

---

## 步骤 4：协议端与 QQ

详见 [连接 QQ / 协议端](guide/connect-qq.md)。Docker 下打开：

`http://<宿主机IP>:8088/protocol/console/`

::: details NapCat 与 Docker 模式
Linux 下管理页使用 **Docker 模式** 拉起 NapCat 时，需在 `pallasbot` 服务挂载 **`/var/run/docker.sock`**（compose 内已注释说明，注意安全）。

自管 NapCat 时，WebSocket：`ws://<可达Bot的地址>:8088/onebot/v11/ws`。
:::

**如何确认成功**：控制台显示在线 Bot；群内 **牛牛帮助** 有响应。

---

## 步骤 5：访问控制台

| 服务 | 地址 |
| --- | --- |
| Web 控制台 | `http://<宿主机>:8088/pallas/` |
| 协议端管理 | `http://<宿主机>:8088/protocol/console/` |

使用启动日志中的口令登录；生产环境勿开 `pallas_webui_dev_mode`。

---

## 日常运维

```bash
docker compose logs -f pallasbot
```

::: details 备份、防火墙与更新
**备份**：`./pallas-bot/data/`、`pallas.toml`、数据库卷（`./mongo/data` 或 `./postgres/data`）

**防火墙**：仅对可信 IP 开放 **8088**；公网请加 HTTPS 与强认证。

**更新**：

```bash
docker compose down
docker compose pull
docker compose up -d
# PostgreSQL profile 时加上 --env-file 与 --profile postgres
```

站点插件若挂载 `./pallas-bot/local/plugins`，需在 `pallas.toml` 设置 `extra_plugin_dirs`。见 [站点定制与更新](architecture/site-customization-and-updates.md)。
:::

::: details 宿主机探活（可选）
Bot 已在容器内运行时：

```bash
uv run python tools/scripts/bot_watchdog.py --docker-container pallasbot --no-spawn
```

容器名须与 compose 中 `container_name` / 服务名一致。详见 [标准部署 · 进程守护](Deployment.md#进程守护脚本可选)。
:::

---

::: details 自建镜像与 `PALLAS_UV_EXTRAS`
官方镜像 `pallasbot/pallas-bot:latest` 为**单进程**用途。自行 `docker build` 时，仓库根目录 **`.dockerignore`** 默认不打包 `tests/`、`docs/`、`.git`、`data/`、`local/` 等。

| 场景 | 建议 `PALLAS_UV_EXTRAS` | 说明 |
| --- | --- | --- |
| 单进程 + MongoDB | `perf` | 默认 compose 栈 |
| 单进程 + PostgreSQL | `perf,pg` | **Dockerfile 默认值** |
| 多进程分片 | `perf,pg,deploy-shard` | 需配置 `REDIS_URL` |
| 4.0 core 仅接话 | `perf,pg` | 默认不装玩法扩展 |
| 4.0 + 常用玩法 | `perf,pg,plugins-game` | 决斗 + 谁是卧底 |
| 4.0 全官方扩展 | `perf,pg,deploy-full` | 决斗 + MAA + 谁是卧底 |
| 4.0 全部官方扩展 | `perf,pg,deploy-all` | 11 个官方扩展包 |

示例：

```bash
docker build \
  --build-arg PALLAS_UV_EXTRAS=perf,pg \
  --build-arg PALLAS_BOT_VERSION=3.0.0 \
  -t pallasbot:local .
```

国内拉取基础镜像失败见下方排障 · `python:3.12-slim`。
:::

::: details 多进程分片（可选）
十余只及以上牛牛、需 hub + worker 时，参考 [`docker-compose.shard.example.yml`](../docker-compose.shard.example.yml)：

- hub 映射 **8088**；worker 映射 **8090、8091…**
- hub 与所有 worker **共用同一份** `pallas.toml` 与 **`data/`** 挂载

说明见 [多进程分片架构](architecture/bot_process_sharding.md)。
:::

---

## 排障

::: details `project name must not be empty`
仓库 compose 已设 `name: pallas-bot`。若仍报错：`docker compose -p pallas-bot up -d`，或避免用特殊字符作当前目录名。
:::

::: details `pallas.toml ... not a directory`
宿主机 `pallas-bot/config/pallas.toml` 被建成了**目录**。删除该目录，重新 `cp config/pallas.example.toml` 为文件后再 `up`。
:::

::: details `help` 告警样式路径不存在
勿将空 `./pallas-bot/resource` 挂到 `/app/resource`；仅挂载 **`voices`** 子目录。
:::

::: details PG：`database "PallasBot" does not exist`
数据卷曾用其他 `POSTGRES_DB` 初始化，与当前 `PG_DB` 不一致。对齐库名或清空 `./postgres/data` 后重建，见 [FAQ](FAQ.md)。
:::

::: details 拉取 `python:3.12-slim` 失败
使用镜像加速或：

```bash
docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .
```
:::

::: details Compose 服务名与 WebSocket
协议端插件按 `pallas.toml` 的 `HOST`/`PORT` 生成 WS；**不会**自动使用 compose 服务名 `pallasbot`。自管 NapCat 且与 Bot 同网络时，可手写 `ws://pallasbot:8088/onebot/v11/ws`。
:::

---

## 接下来

| 我想… | 文档 |
| --- | --- |
| 非 Docker 标准部署 | [标准部署](Deployment.md) |
| 改配置项说明 | [配置要点](Config.md) |
| 装官方扩展 | [安装官方扩展](guide/install-extensions.md) |
| 更多排错 | [FAQ](FAQ.md) |
