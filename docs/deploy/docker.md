# 使用 Docker 部署

完成本页后，Bot、PostgreSQL 和网页控制台会由 Docker Compose 启动。适合希望用官方镜像部署、无需修改源码的使用者。

::: tip
**不要** `git clone` 整仓。镜像内已有代码；本机只需 compose 文件与配置。

依赖：[Docker](https://docs.docker.com/get-docker/)。先确认 Compose 可用：

```bash
docker compose version
```
:::

看到版本信息后，可以继续部署。

## 1. 创建部署目录并下载所需文件

创建一个空的部署目录，并下载三个所需文件：

```bash
mkdir -p ~/pallas-deploy/pallas-bot/config \
         ~/pallas-deploy/pallas-bot/data \
         ~/pallas-deploy/pallas-bot/resource/voices
cd ~/pallas-deploy

BASE=https://raw.githubusercontent.com/PallasBot/Pallas-Bot/main
curl -fsSL -o docker-compose.yml "$BASE/docker-compose.yml"
curl -fsSL -o pallas-bot/config/pallas.toml "$BASE/config/pallas.example.toml"
curl -fsSL -o pallas-bot/config/compose.env "$BASE/config/compose.env.example"
```

::: tip
Windows 可用 Docker Desktop 自带的终端。没有 `curl` 时，用浏览器打开上面三个 URL，把内容存到对应路径即可。

注意：`pallas-bot/config/pallas.toml` 必须是**文件**，不能是目录。
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

::: warning
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

先在 [网页控制台](/guide/web-console) 登录并完成首次设置。然后打开 `http://<主机>:8088/pallas/protocol`，用同一密码登录 → 新建 NapCat → 扫码。群里发 **牛牛帮助**，应能出图。

完整说明见 [连接 QQ](/guide/connect-qq)。

## 日常命令

```bash
docker compose --env-file ./pallas-bot/config/compose.env logs -f pallasbot
docker compose --env-file ./pallas-bot/config/compose.env restart pallasbot
docker compose --env-file ./pallas-bot/config/compose.env pull
docker compose --env-file ./pallas-bot/config/compose.env up -d
docker compose --env-file ./pallas-bot/config/compose.env down
```

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
    image: pallasbot/pallas-bot:latest
    restart: always
    ports:
      - "${BOT_PORT:-8088}:${BOT_LISTEN_PORT:-8088}"
    environment:
      TZ: Asia/Shanghai
      ENVIRONMENT: prod
      APP_MODULE: bot:app
      MAX_WORKERS: 1
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
    image: postgres:16-alpine
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
    image: redis:7-alpine
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
    image: ollama/ollama:latest
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
    image: ollama/ollama:latest
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

::: details MongoDB（3.x 升级沿用）
`pallas.toml` 设 `db_backend = "mongodb"` 并填写 `[bootstrap.mongo]`，然后：

```bash
docker compose --env-file ./pallas-bot/config/compose.env --profile mongo up -d
```

根目录 compose 默认只起 PostgreSQL；Mongo 需显式加 `--profile mongo`。
:::

::: details 备份与防火墙
- 备份：`./pallas-bot/data/`、`pallas.toml`、`./postgres/data`（或 `./mongo/data`）
- 防火墙：仅对可信 IP 开放 **8088**；公网请加 HTTPS
:::

::: details 自建镜像与 extras
官方镜像偏单进程用途。自行 `docker build` 时可用 `--build-arg PALLAS_UV_EXTRAS=perf`（PG 驱动已在主依赖）。国内拉基础镜像失败可用 `BASE_IMAGE` 换镜像站前缀。
:::

::: details 多进程分片
官方根目录 Compose 面向单进程。源码部署优先 `./scripts/run_sharded_bot.sh`（见 [分片部署](/maintainer/deploy/sharded)）。若坚持用 Docker，可将下面示例另存为 `docker-compose.shard.yml`（hub + 2 worker；按需复制 worker 段并改端口 / `PALLAS_SHARD_ID`）。协议端反向 WS 须连 **worker** 端口（8090+），不是 hub 8088。`pallas.toml` 的 `[env]` 可设 `REDIS_URL=redis://redis:6379/0`，或依赖下方环境变量。

```yaml
name: pallas-bot-shard

x-pallas-common: &pallas-common
  image: pallasbot/pallas-bot:latest
  restart: always
  environment: &pallas-env
    TZ: Asia/Shanghai
    ENVIRONMENT: prod
    MAX_WORKERS: 1
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
    image: postgres:16-alpine
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
    image: redis:7-alpine
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

::: details `pallas.toml ... not a directory`
宿主机路径被建成了目录。删掉后重新下载为**文件**再 `up`。
:::

::: details `database "PallasBot" does not exist`
旧数据卷库名与当前 `PG_DB` 不一致。对齐库名，或清空 `./postgres/data` 后重建（会丢数据）。见 [FAQ](/deploy/faq)。
:::

::: details `help` 样式路径不存在
勿把空 `resource` 整目录挂到 `/app/resource`；只挂 `voices`（与官方 compose 一致）。
:::

::: details `project name must not be empty`
仓库 compose 已设 `name: pallas-bot`。仍报错时用 `docker compose -p pallas-bot ...`，或避免特殊字符目录名。
:::
