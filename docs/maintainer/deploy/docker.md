# 使用 Docker 部署

> **目标**：用 Docker Compose 启动 Bot、PostgreSQL 和网页控制台  
> **准备**：安装 Docker；镜像内已有代码，本机只需 compose 文件与配置  
> **完成之后**：服务已启动，浏览器可打开控制台；适合没有源码开发需求的部署

::: warning 注意：无需 clone 整仓
镜像内已包含代码，**不要** `git clone` Pallas-Bot 仓库，本机只需要 compose 文件与配置文件。
:::

先确认 Docker 可用：

```bash
docker compose version
```

看到版本信息后，可以继续部署。

## 1. 创建部署目录并下载所需文件

创建一个空的部署目录，并下载三个所需文件：

::: code-group

```bash [Linux / macOS]
mkdir -p ~/pallas-deploy/pallas-bot/config \
         ~/pallas-deploy/pallas-bot/data \
         ~/pallas-deploy/pallas-bot/resource/voices
cd ~/pallas-deploy

BASE=https://raw.githubusercontent.com/PallasBot/Pallas-Bot/main
curl -fsSL -o docker-compose.yml "$BASE/docker-compose.yml"
curl -fsSL -o pallas-bot/config/pallas.toml "$BASE/config/pallas.example.toml"
curl -fsSL -o pallas-bot/config/compose.env "$BASE/config/compose.env.example"
```

```powershell [Windows PowerShell]
New-Item -ItemType Directory -Force -Path pallas-deploy/pallas-bot/config, pallas-deploy/pallas-bot/data, pallas-deploy/pallas-bot/resource/voices | Out-Null
Set-Location pallas-deploy

$base = "https://raw.githubusercontent.com/PallasBot/Pallas-Bot/main"
Invoke-WebRequest "$base/docker-compose.yml" -OutFile docker-compose.yml
Invoke-WebRequest "$base/config/pallas.example.toml" -OutFile pallas-bot/config/pallas.toml
Invoke-WebRequest "$base/config/compose.env.example" -OutFile pallas-bot/config/compose.env
```

:::

::: tip Windows 用户
在 PowerShell 中运行上面的 Windows 命令。若已在 Git Bash 或 WSL 中工作，也可使用 Linux / macOS 这一组命令。
:::

::: warning 注意：配置文件是文件不是目录
`pallas-bot/config/pallas.toml` 必须是**文件**。若之前启动过且把它建成了目录，先删除再重新下载。
:::

目录中已有 `docker-compose.yml`、`pallas-bot/config/pallas.toml` 和 `pallas-bot/config/compose.env` 后，文件已准备完成。

## 2. 让 Bot 与数据库使用相同配置

编辑 **`pallas-bot/config/pallas.toml`**：

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "postgresql"

[bootstrap.postgres]
host = "postgres"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

`compose.env` 里的 `PG_USER` / `PG_PASSWORD` / `PG_DB` 与上面保持一致（默认已对齐）。

::: warning 注意：容器内主机名
`host` 填 Compose 服务名 **`postgres`**，不要填 `127.0.0.1`（容器内指不到库）。
:::

保存后，Bot 和 PostgreSQL 会使用同一组数据库连接信息。

## 3. 启动服务并确认可访问

```bash
docker compose --env-file ./pallas-bot/config/compose.env up -d
```

首次启动会拉取镜像并初始化数据库，控制台初始密码会出现在 Bot 日志中。接着检查状态：

```bash
docker compose --env-file ./pallas-bot/config/compose.env ps
curl -s http://127.0.0.1:8088/pallas/api/health
docker compose --env-file ./pallas-bot/config/compose.env logs pallasbot | head -80
```

`docker compose ps` 显示服务运行，健康检查可访问且日志没有启动错误时，说明服务已启动。浏览器打开 `http://127.0.0.1:8088/pallas/`，使用日志里的控制台密码登录。

## 接下来：登录控制台并连接 QQ

先在 [网页控制台](/guide/web-console) 登录并完成首次设置。随后可在协议端管理中托管 NapCat / SnowLuma，或让已有 OneBot V11 协议端反向连接。群里发 **牛牛帮助**，应能出图。

完整说明见 [连接 QQ](/guide/connect-qq)。

## 日常命令

```bash
docker compose --env-file ./pallas-bot/config/compose.env logs -f pallasbot
docker compose --env-file ./pallas-bot/config/compose.env restart pallasbot
docker compose --env-file ./pallas-bot/config/compose.env pull
docker compose --env-file ./pallas-bot/config/compose.env up -d
docker compose --env-file ./pallas-bot/config/compose.env down
```

## 下载慢与镜像源

先按失败对象选择配置；下面三类来源互不替代。

### 拉取 Docker 镜像

`docker pull` 或 `docker compose pull` 访问 Docker Hub 失败时，可为宿主机 Docker daemon 配置 Registry mirror。Linux 通常编辑 `/etc/docker/daemon.json`，将 `https://<你的 Docker Registry mirror>` 合并到已有 JSON，不要覆盖其他 daemon 配置：

```json
{
  "registry-mirrors": ["https://<你的 Docker Registry mirror>"]
}
```

保存后重启并验证；Docker Desktop 用户在设置页的 Docker Engine 中修改同一字段：

```bash
sudo systemctl restart docker
docker info --format '{{json .RegistryConfig.Mirrors}}'
```

如果镜像服务要求使用完整代理地址，而不是 daemon mirror，可在 `pallas-bot/config/compose.env` 覆盖 Compose 镜像：

```dotenv
PALLAS_BOT_IMAGE=<Registry>/pallasbot/pallas-bot:latest
POSTGRES_IMAGE=<Registry>/library/postgres:16-alpine
MONGO_IMAGE=<Registry>/library/mongo:8.0.10-noble
REDIS_IMAGE=<Registry>/library/redis:7-alpine
OLLAMA_IMAGE=<Registry>/ollama/ollama:latest
PALLAS_AI_IMAGE=<Registry>/pallasbot/pallas-bot-ai:slim
```

不同服务的路径规则由 Registry 提供方决定。启动前检查 Compose 最终采用的地址：

```bash
docker compose --env-file ./pallas-bot/config/compose.env config --images
```

### 自建 Bot 镜像与 Python 依赖

本地构建时，`BASE_IMAGE` 替换 Dockerfile 的 Python 基础镜像，`UV_DEFAULT_INDEX` 指定安装 uv 和项目依赖所用的 Python 包索引：

```bash
docker build \
  --build-arg BASE_IMAGE=<Registry>/library/python:3.12-slim \
  --build-arg UV_DEFAULT_INDEX=https://<你的 Python 包索引>/simple \
  -t pallasbot:local .
```

运行中的 Bot / work 容器安装插件时也会读取 `compose.env` 的 `UV_DEFAULT_INDEX`；不设置则使用 `https://pypi.org/simple`。直接使用 pip 时另配 `PIP_INDEX_URL`。

### WebUI Git 镜像源

Bot 启动后可在控制台的 **更新管理 → 镜像源** 或 **插件商店 → 镜像源** 设置首选 Git 镜像、分目标覆盖并测试连通性。它用于 Bot/WebUI 更新、GitHub Release、Git clone 和插件资源下载。

该配置**不影响** `docker pull`、Dockerfile 基础镜像或 uv/PyPI 依赖下载；这些仍使用上面对应的 Docker 与 Python 配置。

## 容器内更新与 Docker 权限

控制台可以更新 Bot 正式 Release、WebUI 和插件。Bot Release 会覆盖当前容器，普通 `docker compose restart` 不会丢失；容器重建后会恢复为镜像版本。持久更新仍使用上面的 `pull` + `up -d`。

官方镜像默认包含 Docker CLI。只有让协议端管理 NapCat / SnowLuma 容器时，才按 `docker-compose.yml` 注释挂载 `/var/run/docker.sock`；该 socket 接近宿主机 root 权限，不用于管理 Bot 自身、AI、数据库、Redis 或 Ollama。自建镜像可用 `--build-arg INSTALL_DOCKER_CLI=0` 移除 CLI。

AI Runtime、Redis、Ollama 和数据库始终由 Compose 或外部运维负责。控制台不会因为拥有 Docker socket 而创建、更新或重建这些服务。

::: details 全栈（Bot + PG + Redis + Ollama + AI）
仓库根目录只提供默认 `docker-compose.yml`（Bot + PostgreSQL）。需要 AI Runtime / Ollama 时，将下面 YAML 另存为部署目录中的 `docker-compose.full.yml`，再启动。

准备目录与 `pallas.toml` / `compose.env` 与上文相同；另建 `pallas-bot-ai/logs`。`[bootstrap.postgres].host` 填 **`postgres`**。

```yaml
# Bot + PostgreSQL + Redis + Ollama + AI Runtime
# 启动: docker compose -f docker-compose.full.yml --env-file ./pallas-bot/config/compose.env up -d
# 可选预拉模型: 追加 --profile pull-models
# GPU: 再叠加下文 docker-compose.full.gpu.yml

name: pallas-full

services:
  pallasbot:
    container_name: pallasbot
    image: ${PALLAS_BOT_IMAGE:-pallasbot/pallas-bot:latest}
    restart: always
    ports:
      - "${BOT_PORT:-8088}:${BOT_LISTEN_PORT:-8088}"
    environment:
      TZ: Asia/Shanghai
      ENVIRONMENT: prod
      APP_MODULE: bot:app
      MAX_WORKERS: 1
      UV_DEFAULT_INDEX: ${UV_DEFAULT_INDEX:-https://pypi.org/simple}
      PORT: ${BOT_LISTEN_PORT:-8088}
      DB_BACKEND: postgresql
      PG_HOST: postgres
      PG_PORT: "5432"
      PG_USER: ${PG_USER:-pallas}
      PG_PASSWORD: ${PG_PASSWORD:-pallas}
      PG_DB: ${PG_DB:-PallasBot}
      AI_SERVER_HOST: pallasbot-ai
      AI_SERVER_PORT: "9099"
      LLM_CHAT_ENABLED: "true"
    networks:
      - pallas-full
    volumes:
      - ./pallas-bot/resource/voices:/app/resource/voices
      - ./pallas-bot/config/pallas.toml:/app/config/pallas.toml
      - ./pallas-bot/data:/app/data
      - ./pallas-bot/local/plugins:/app/local/plugins
      - ./pallas-bot-ai/logs:/ai-logs:ro
    depends_on:
      postgres:
        condition: service_healthy
      pallasbot-ai:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    container_name: pallasbot_postgres
    image: ${POSTGRES_IMAGE:-postgres:16-alpine}
    restart: always
    command:
      - postgres
      - -c
      - shared_preload_libraries=pg_stat_statements
      - -c
      - track_io_timing=on
      - -c
      - idle_in_transaction_session_timeout=15s
    environment:
      TZ: Asia/Shanghai
      POSTGRES_USER: ${PG_USER:-pallas}
      POSTGRES_PASSWORD: ${PG_PASSWORD:-pallas}
      POSTGRES_DB: ${PG_DB:-PallasBot}
    networks:
      - pallas-full
    volumes:
      - ./postgres/data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$$POSTGRES_USER\" -d \"$$POSTGRES_DB\""]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s

  redis:
    image: ${REDIS_IMAGE:-redis:7-alpine}
    container_name: pallas-full-redis
    command: redis-server --appendonly yes
    networks:
      - pallas-full
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 5s

  ollama:
    image: ${OLLAMA_IMAGE:-ollama/ollama:latest}
    container_name: pallas-full-ollama
    networks:
      - pallas-full
    volumes:
      - ollama_data:/root/.ollama
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "ollama list || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 30s

  ollama-init:
    profiles: ["pull-models"]
    image: ${OLLAMA_IMAGE:-ollama/ollama:latest}
    container_name: pallas-full-ollama-init
    networks:
      - pallas-full
    volumes:
      - ollama_data:/root/.ollama
    environment:
      OLLAMA_MODEL: ${LLM_MODEL:-qwen2.5:7b}
      OLLAMA_CATEGORIZER_MODEL: ${LLM_CATEGORIZER_MODEL:-qwen2.5:0.5b}
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        until wget -q -O- http://ollama:11434/api/tags >/dev/null 2>&1; do sleep 2; done
        ollama pull "$${OLLAMA_MODEL:-qwen2.5:7b}"
        ollama pull "$${OLLAMA_CATEGORIZER_MODEL:-qwen2.5:0.5b}"
    depends_on:
      ollama:
        condition: service_healthy
    restart: "no"

  pallasbot-ai:
    image: ${PALLAS_AI_IMAGE:-pallasbot/pallas-bot-ai:slim}
    container_name: pallasbot-ai
    ports:
      - "${AI_SERVER_PORT:-9099}:9099"
    environment:
      TZ: Asia/Shanghai
      REDIS_URL: redis://redis:6379/0
      LLM_SESSION_BACKEND: redis
      CALLBACK_HOST: pallasbot
      CALLBACK_PORT: ${BOT_LISTEN_PORT:-8088}
      LLM_CHAT_ENABLED: "true"
      LLM_PROVIDER_MODE: ${LLM_PROVIDER_MODE:-local_only}
      LLM_BACKEND_URL: http://ollama:11434
      LLM_MODEL: ${LLM_MODEL:-qwen2.5:7b}
      LLM_CATEGORIZER_MODEL: ${LLM_CATEGORIZER_MODEL:-qwen2.5:0.5b}
      LLM_AUTO_START: "false"
      CELERY_TASK_PACKAGES: llm
      AI_ENABLE_MEDIA_WORKER: "0"
      PALLAS_AI_API_TOKEN: ${PALLAS_AI_API_TOKEN:-}
    networks:
      - pallas-full
    volumes:
      - ./pallas-bot-ai/logs:/server/logs
    depends_on:
      redis:
        condition: service_healthy
      ollama:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9099/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s

networks:
  pallas-full:

volumes:
  redis_data:
  ollama_data:
```

```bash
docker compose -f docker-compose.full.yml --env-file ./pallas-bot/config/compose.env up -d
# 可选预拉 Ollama 模型: 追加 --profile pull-models
```

默认 AI 镜像为 **`pallasbot/pallas-bot-ai:slim`**，仅供媒体任务与遗留 RWKV 使用，不预拉模型。Bot 容器通过 **`AI_SERVER_HOST=pallasbot-ai`** 连接已启用的 AI 服务。LLM 聊天默认走 Bot 内核 Provider，不必依赖 9099。始终验收 `8088`；启用 AI Runtime 时再验收 `9099`。

`BOT_PORT` = 宿主机访问端口；`BOT_LISTEN_PORT` = 容器内监听（默认皆 8088）。AI 回调走 `BOT_LISTEN_PORT`，只改宿主机端口时勿动它。

有 NVIDIA GPU 且需唱歌/TTS 时，在 `compose.env` 设 `PALLAS_AI_IMAGE=pallasbot/pallas-bot-ai:latest`，并将下面内容另存为 `docker-compose.full.gpu.yml` 后叠加：

```yaml
# GPU 覆盖层（需 NVIDIA container toolkit）
# docker compose -f docker-compose.full.yml -f docker-compose.full.gpu.yml \
#   --env-file ./pallas-bot/config/compose.env up -d

services:
  ollama:
    runtime: nvidia
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD-SHELL", "ollama list >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1"]
      interval: 5m
      timeout: 15s
      retries: 2
      start_period: 60s
```
:::

::: details 备选：MongoDB（3.x 升级沿用）
`pallas.toml` 设 `db_backend = "mongodb"` 并填写 `[bootstrap.mongo]`，然后：

```bash
docker compose --env-file ./pallas-bot/config/compose.env --profile mongo up -d
```

根目录 compose 默认只起 PostgreSQL；Mongo 需显式加 `--profile mongo`。
:::

::: details 备份与防火墙
- 备份：`./pallas-bot/data/`、`pallas.toml`、`./postgres/data`（或 `./mongo/data`）
- 防火墙：仅对可信 IP 开放 **8088**；公网加 HTTPS
:::

::: details 自建镜像与 extras
官方镜像偏单进程用途。自行 `docker build` 时可用 `--build-arg PALLAS_UV_EXTRAS=perf`（PG 驱动已在主依赖）。基础镜像与 Python 包索引参数见上方 [下载慢与镜像源](#下载慢与镜像源)。
:::

::: details 多进程分片
官方根目录 Compose 面向单进程。分片可使用源码脚本（见 [分片部署](/maintainer/deploy/sharded)），也可将下面示例另存为 `docker-compose.shard.yml`（hub + 2 worker；按需复制 worker 段并改端口 / `PALLAS_SHARD_ID`）。协议端反向 WS 须连 **worker** 端口（8090+），不是 hub 8088。`pallas.toml` 的 `[env]` 可设 `REDIS_URL=redis://redis:6379/0`，或依赖下方环境变量。

```yaml
name: pallas-bot-shard

x-pallas-common: &pallas-common
  image: ${PALLAS_BOT_IMAGE:-pallasbot/pallas-bot:latest}
  restart: always
  environment: &pallas-env
    TZ: Asia/Shanghai
    ENVIRONMENT: prod
    MAX_WORKERS: 1
    UV_DEFAULT_INDEX: ${UV_DEFAULT_INDEX:-https://pypi.org/simple}
    PALLAS_SHARD_ENABLED: "true"
    PG_HOST: postgres
    PG_PORT: "5432"
    REDIS_URL: redis://redis:6379/0
  volumes: &pallas-volumes
    - ./pallas-bot/resource/voices:/app/resource/voices
    - ./pallas-bot/config/pallas.toml:/app/config/pallas.toml
    - ./pallas-bot/data:/app/data
    - ./pallas-bot/local/plugins:/app/local/plugins
  networks:
    - pallasbot
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy

services:
  pallas-hub:
    <<: *pallas-common
    container_name: pallas-hub
    ports:
      - "8088:8088"
    environment:
      <<: *pallas-env
      APP_MODULE: bot_hub:app
      PALLAS_BOT_ROLE: hub
      PORT: "8088"
      PALLAS_SHARD_WORKER_BASE_PORT: "8090"
      PALLAS_SHARD_BOTS_PER: "5"

  pallas-worker-0:
    <<: *pallas-common
    container_name: pallas-worker-0
    ports:
      - "8090:8090"
    environment:
      <<: *pallas-env
      APP_MODULE: bot_worker:app
      PALLAS_BOT_ROLE: worker
      PALLAS_SHARD_ID: "0"
      PORT: "8090"

  pallas-worker-1:
    <<: *pallas-common
    container_name: pallas-worker-1
    ports:
      - "8091:8091"
    environment:
      <<: *pallas-env
      APP_MODULE: bot_worker:app
      PALLAS_BOT_ROLE: worker
      PALLAS_SHARD_ID: "1"
      PORT: "8091"

  postgres:
    container_name: pallasbot_postgres
    image: ${POSTGRES_IMAGE:-postgres:16-alpine}
    restart: always
    environment:
      TZ: Asia/Shanghai
      POSTGRES_USER: ${PG_USER:-pallas}
      POSTGRES_PASSWORD: ${PG_PASSWORD:-pallas}
      POSTGRES_DB: ${PG_DB:-PallasBot}
    networks:
      - pallasbot
    volumes:
      - ./postgres/data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$$POSTGRES_USER\" -d \"$$POSTGRES_DB\""]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 15s

  redis:
    container_name: pallasbot_redis
    image: ${REDIS_IMAGE:-redis:7-alpine}
    restart: always
    command: ["redis-server", "--appendonly", "yes"]
    networks:
      - pallasbot
    volumes:
      - ./redis/data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 5s

networks:
  pallasbot:
```

```bash
docker compose -f docker-compose.shard.yml --env-file ./pallas-bot/config/compose.env up -d
```
:::

## 排障

::: details 排障：配置路径被建为目录
宿主机路径被建成了目录。删掉后重新下载为**文件**再 `up`。
:::

::: details 排障：数据库不存在
旧数据卷库名与当前 `PG_DB` 不一致。对齐库名，或清空 `./postgres/data` 后重建（会丢数据）。见 [FAQ](/deploy/faq)。
:::

::: details 排障：帮助图样式路径缺失
勿把空 `resource` 整目录挂到 `/app/resource`；只挂 `voices`（与官方 compose 一致）。
:::

::: details 排障：Compose 项目名缺失
仓库 compose 已设 `name: pallas-bot`。仍报错时用 `docker compose -p pallas-bot ...`，或避免特殊字符目录名。
:::
