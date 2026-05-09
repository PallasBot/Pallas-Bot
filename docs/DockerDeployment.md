# Pallas-Bot Docker 部署

> 导航：[`README`](../README.md) · [`标准部署`](Deployment.md) · [`3.0 迁移`](Migration-v3.md) · [`FAQ`](FAQ.md)

如果你不想自己配置环境，可以使用 `Docker Compose` 一键部署已构建好的镜像。拉取镜像请优先使用与你的版本对应的 **Release** 标签。在 **`.env`** 里选择 **`DB_BACKEND=mongo`** 或 **`DB_BACKEND=postgres`** 并填写对应连接信息即可。你需要安装 `Docker` 与 `Docker Compose`（较新版本的 `Docker` 已集成 `Compose` 插件），镜像支持 `amd64` 与 `arm64`。

## 准备工作

### 安装 `Docker` 与 `Docker Compose`

- [Windows Docker Desktop 安装](https://docs.docker.com/desktop/install/windows-install/) ，推荐使用基于 [WSL 2](https://learn.microsoft.com/zh-cn/windows/wsl/install) 的 `Docker CE`。

- [Linux Docker 安装](https://docs.docker.com/engine/install/ubuntu/)，推荐使用 `curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun` 命令一键安装。

- 较新版本的 `Docker` 已集成 `Compose` 插件，可以通过 `docker compose version` 查看 `Compose` 插件是否已安装。

- 如果你需要为之前已经安装过的老版本 `Docker` 安装 `Docker Compose` 插件，推荐 [单独安装 Docker Compose](https://docs.docker.com/compose/install/other/)。Windows 用户可以直接在 `Docker Desktop` 中启用 `Docker Compose`（`Settings -> General -> Use Docker Compose V2`）。

- （可选）Linux Rootless 模式
  如果你希望以非 root 用户运行 Docker，可以参考 [Docker Rootless 模式](https://docs.docker.com/engine/security/rootless/)。
  如果你使用的是一键安装方式，可以使用以下命令配置 Rootless 模式：

    ```bash
    sudo apt-get install -y uidmap
    dockerd-rootless-setuptool.sh install
    ```

如果你使用的是 Linux 一键安装方式，安装脚本会为你自动配置 Docker 镜像加速。其他安装方式推荐手动[配置镜像加速](https://www.runoob.com/docker/docker-mirror-acceleration.html)。

### 配置 docker-compose.yml

1. 复制一份 [docker-compose.yml](../docker-compose.yml) 到本地单独目录，按需修改 `volumes` 路径：

    ```yml
    ...
    volumes:
        - ./pallas-bot/resource/voices:/app/resource/voices
        - ./pallas-bot/.env:/app/.env
        - ./pallas-bot/data:/app/data
    ...
      - ./mongo/data:/data/db
      - ./mongo/logs:/var/log/mongodb
    ...
      - ./postgres/data:/var/lib/postgresql/data   # 仅在使用 --profile postgres 时创建
    ```

    说明：

    - **`./pallas-bot/.env` 必须是宿主机上的一个「文件」**（从仓库根目录复制 [`.env`](../.env) 后按注释填写）。若该路径不存在就执行 `compose up`，在 Windows 上有时会被自动建成**同名文件夹**，再启动就会报 **`mounting ... .env ... not a directory` / `directory onto file`**：请删除错误的 `.env` 目录，改放真正的 `.env` 文件后再启动。
    - **`resource/voices`** 单独挂载：持久化语音文件。**不要**把宿主机空目录挂到 **`/app/resource` 根目录**，否则会盖住镜像内的 **`resource/styles/default`**（`help` 插件），出现「样式路径不存在」告警。
    - **`pallas-bot/data`** 映射到容器内 **`/app/data`**，用于持久化 **协议端管理**（`pallas_protocol`）的实例与 `runtime_profile.json` 等；不映射则容器删除后配置会丢。
    - **`postgres` 服务**默认带 **`profiles: ["postgres"]`**，只有加 `--profile postgres` 才会启动；默认栈里 **只有 MongoDB** 作为数据库容器。

2. 复制 [`.env`](../.env) 到映射路径（如 `./pallas-bot/.env`），按注释填写。控制台与协议端管理页使用浏览器登录（口令哈希持久化在 `data/pallas_console/`）。

3. **数据后端二选一**

    - **MongoDB（默认）**：直接 `docker compose up -d`。`.env` 中 `DB_BACKEND=mongo`（或默认）。compose 已为 `pallasbot` 注入 **`MONGO_HOST=mongodb`**、**`MONGO_PORT=27017`**。若你自建 Mongo 或改服务名，请同步改 compose 或 `.env`。
    - **PostgreSQL**：在 **`pallas-bot/.env`** 中设置 `DB_BACKEND=postgres`，并填写 **`PG_USER`** / **`PG_PASSWORD`** / **`PG_DB`**。compose 已为 `pallasbot` 注入 **`PG_HOST=postgres`**、**`PG_PORT=5432`**，无需在 `.env` 里再写 `127.0.0.1`。启动内置数据库时请执行 **`docker compose --env-file ./pallas-bot/.env --profile postgres up -d`**，以便 compose 把 **`PG_USER`/`PG_PASSWORD`/`PG_DB`** 插值写入 `postgres` 容器的 **`POSTGRES_*`**。若使用自建 Postgres，可不加 `--profile postgres`，删掉 compose 里 **`PG_HOST`/`PG_PORT`** 覆盖并在 `.env` 写明真实地址，并从 `depends_on` 中视情况移除对内置 `postgres` 的等待（见仓库 `docker-compose.yml` 注释）。

    从历史数据迁移请参考 [`3.0 迁移指南`](Migration-v3.md)。

4. **QQ / NapCat 与协议端管理**

    默认 **不再** 在 Compose 中编排独立 **`napcat`** 容器；请在浏览器打开 **`http://<宿主机>:8088/protocol/console/`**（端口随映射变化），在 **协议端管理** 中创建实例并登录。管理页会按当前 Bot 的运行方式（本机进程或 Docker 等）自动填写 OneBot WebSocket 等连接信息，一般无需手动改；自管 NapCat 或网络异常时再查 [`pallas_protocol` 说明](plugins/pallas_protocol/README.md)。

    - **Linux** 且管理页里使用 **Docker 模式** 拉起 NapCat：需在 `pallasbot` 服务上挂载 **`/var/run/docker.sock`**（`docker-compose.yml` 内已用注释标出；有安全风险，生产环境请加固）。
    - 若仍希望 **单独** 起一个 NapCat 容器，可自行写 compose 并做好与 Bot 的网络互通；注意与协议端管理不要 **重复登录同一账号**。

## 启动与使用

### 启动

```bash
# 仅 MongoDB（默认）
docker compose up -d

# 需要本 compose 内的 PostgreSQL 时（PG_* 写在 pallas-bot/.env）
docker compose --env-file ./pallas-bot/.env --profile postgres up -d
```

### 查看日志

在 `docker-compose.yml` 所在目录执行：

```bash
docker compose logs -f pallasbot
```

### 访问 Web 控制台与协议端管理

（默认映射宿主机 `8088`，若已修改 `ports` 请替换。）

- **Web 控制台**：`http://<宿主机ip>:8088/pallas/`（HTTP API 一般为 `http://<宿主机ip>:8088/pallas/api`）
- **协议端管理**：`http://<宿主机ip>:8088/protocol/console/`（与控制台共用登录；详见 [`pallas_protocol`](plugins/pallas_protocol/README.md)）

写操作需先登录（会话 Cookie）；勿在生产环境开启 `pallas_webui_dev_mode`。

## 排障

### `project name must not be empty`

Compose 默认用**当前文件夹名**作为项目名；目录名为中文等时，部分 Docker Desktop 版本会推出**空项目名**从而报错。本仓库 [`docker-compose.yml`](../docker-compose.yml) 已在顶层设置 **`name: pallas-bot`** 规避该问题。

若你使用的 `docker-compose.yml` 尚无此行，可任选其一：

- 启动时指定项目名：`docker compose -p pallas-bot --profile postgres up -d`
- PowerShell：`$env:COMPOSE_PROJECT_NAME = "pallas-bot"` 后再执行 `docker compose ...`

同一台机器多套实例时请改用不同项目名（例如 `-p pallasbot-home2`），避免网络/容器名冲突。

### `help` 告警「样式路径不存在 `/app/resource/styles/default`」

多为 **Compose 把整条 `./pallas-bot/resource` 挂到 `/app/resource`**，宿主机目录里没有从仓库带过来的 **`styles/default`**，把镜像内自带样式**遮住**了。请改用仓库当前写法：**只挂载 `./pallas-bot/resource/voices:/app/resource/voices`**，或保证宿主机 `resource` 下包含与仓库一致的 **`styles/default`**。

### PG 日志 `FATAL: database "PallasBot" does not exist`

**不是** Postgres 容器坏了，而是：**当前数据目录里根本没有名为 `PallasBot` 的库**，而 Bot 的 **`PG_DB`**（默认 `PallasBot`）正在连这个库。

常见原因：

1. **数据卷是以前用别的 `POSTGRES_DB` 初始化过的**（例如旧 compose 默认建过库名 **`pallas`**）。Postgres 官方镜像**只在数据目录为空时**根据 `POSTGRES_DB` 建库，**改环境变量不会自动改名/建新库**。
2. **`.env` 里 `PG_DB` 与 compose 插值出的 `POSTGRES_DB` 不一致**（且卷里只有其中一侧的库）。

处理任选其一：

- **对齐名字**：把 **`pallas-bot/.env`** 里的 **`PG_DB`** 改成与卷里**已有**库名一致（若当初建的是 `pallas` 就写 `pallas`），并 **`docker compose restart pallasbot`**。
- **重建空卷（会删库）**：`docker compose --profile postgres down`，删除宿主机 **`./postgres/data`** 目录，再 **`docker compose --env-file ./pallas-bot/.env --profile postgres up -d`**，让镜像按当前 **`POSTGRES_DB`**（默认与 **`PG_DB`** 一致为 **`PallasBot`**）重新初始化。
- **保留数据手动建库**：`docker exec -it pallasbot_postgres psql -U <PG_USER> -d postgres -c 'CREATE DATABASE "PallasBot";'`（库名与 **`PG_DB`** 一致即可）。

### `python:3.12-slim` / `registry-1.docker.io` 拉取失败、`EOF`、`connectex`

访问 **Docker Hub** 不稳定时，构建会在 **`FROM python`** 或解析 manifest 阶段失败。可选做法：

1. **构建参数换基础镜像前缀**（仓库 [`Dockerfile`](../Dockerfile) 支持 **`BASE_IMAGE`**）：

    ```bash
    docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .
    ```

    若某镜像站不可用，请换你环境能访问的 **`library/python:3.12-slim`** 同步源（需与官方标签一致或兼容）。

2. **Docker Desktop**：在 **Settings → Docker Engine** 中为 `registry-mirrors` 配置加速，并重试 `docker build`。

3. **代理 / VPN**：让 Docker 守护进程能访问 `registry-1.docker.io`。

### `mounting ... /.env ... not a directory` / `Are you trying to mount a directory onto a file`

宿主机上 `./pallas-bot/.env` 与容器内 **`/app/.env`（文件）** 类型不一致时会出现。常见原因：`pallas-bot/.env` 实际是**文件夹**，或路径写错。处理：删掉宿主机上误建的 **`.env` 目录**，从仓库复制 **`.env` 文件**到 `pallas-bot/.env`，保存为普通文本文件后再 `docker compose up`。

### Compose 服务名 `pallasbot` 与内网 WebSocket

- **不必**为了协议端专门「取消」自定义网络：Compose 会为项目建网络，**服务名 DNS**（如 `pallasbot`）只在该网络内的容器之间生效；删掉显式 `networks:` 仍会生成默认网络，**并不能**让协议端 Docker 模式自动改用 `pallasbot` 主机名。
- **协议端管理**写入 **`onebot*.json`** 时，依据的是 **`.env` / 驱动里的 `HOST`、`PORT` 等** 解析出 WS，再在 **Linux Docker 模式**下把主机替换为解析后的 **`PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`**（留空时 Linux **`bridge`** 一般为**宿主机在容器视角的网关 IP**；见插件文档），**不会**根据 Compose 服务名自动填 `pallasbot`。
- 若你**自行**把 NapCat 写成与 `pallasbot` **同一 Compose 网络**的 service，则可在 NapCat 里把 OneBot 客户端 URL 写成 **`ws://pallasbot:<PORT>/onebot/v11/ws`**（明文 WebSocket、常见内网无 TLS）；这与当前协议端插件 **`docker run` 默认桥接网络** 是两条路径。

## 后续更新

```bash
docker compose down
docker compose pull
docker compose up -d
# 若使用 postgres profile：
# docker compose --env-file ./pallas-bot/.env --profile postgres down
# docker compose pull
# docker compose --env-file ./pallas-bot/.env --profile postgres up -d
```
