# 使用 Docker 部署

::: tip
**不要** `git clone` 整仓。镜像内已有代码；本机只需 compose 文件与配置。

依赖：[Docker](https://docs.docker.com/get-docker/)。确认：

```bash
docker compose version
```
:::

## 1. 准备目录

建一个空的部署目录，只下载三个文件：

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

## 2. 改配置

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

## 3. 启动

```bash
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres up -d
```

看一眼状态：

```bash
docker compose ps
curl -s http://127.0.0.1:8088/pallas/api/health
docker compose logs pallasbot | head -80
```

浏览器打开 `http://127.0.0.1:8088/pallas/`，用日志里的控制台密码登录。

## 4. 连接 QQ

打开 `http://<主机>:8088/pallas/protocol`，用同一密码登录 → 新建 NapCat → 扫码。群里发 **牛牛帮助**，应能出图。

完整说明见 [连接 QQ](/guide/connect-qq)。

## 下一步

▶ [连接 QQ](/guide/connect-qq)

## 日常命令

```bash
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres logs -f pallasbot
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres restart pallasbot
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres pull
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres up -d
docker compose --env-file ./pallas-bot/config/compose.env --profile postgres down
```

::: details 全栈（Bot + PG + Redis + Ollama + AI）
再下载 `docker-compose.full.yml`：

```bash
curl -fsSL -o docker-compose.full.yml \
  https://raw.githubusercontent.com/PallasBot/Pallas-Bot/main/docker-compose.full.yml
docker compose -f docker-compose.full.yml --env-file ./pallas-bot/config/compose.env up -d
# 可选预拉 Ollama 模型: 追加 --profile pull-models
```

默认 AI 镜像为 **`pallasbot/pallas-bot-ai:slim`**（LLM-only，不预拉模型）；模型可在 WebUI「AI 配置」拉取。有 NVIDIA GPU 且需唱歌/TTS 时，在 `compose.env` 设 `PALLAS_AI_IMAGE=pallasbot/pallas-bot-ai:latest` 并叠加 `docker-compose.full.gpu.yml`。`8088` 与 `9099` 的 health 都正常即可。
:::

::: details MongoDB（3.x 升级沿用）
`pallas.toml` 设 `db_backend = "mongodb"` 并填写 `[bootstrap.mongo]`，然后：

```bash
docker compose up -d
```
:::

::: details 备份与防火墙
- 备份：`./pallas-bot/data/`、`pallas.toml`、`./postgres/data`（或 `./mongo/data`）
- 防火墙：仅对可信 IP 开放 **8088**；公网请加 HTTPS
:::

::: details 自建镜像与 extras
官方镜像偏单进程用途。自行 `docker build` 时可用 `--build-arg PALLAS_UV_EXTRAS=perf`（PG 驱动已在主依赖）。国内拉基础镜像失败可用 `BASE_IMAGE` 换镜像站前缀。
:::

::: details 多进程分片
参考仓库 [`docker-compose.shard.example.yml`](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.shard.example.yml)；说明见 [分片部署](/maintainer/deploy/sharded)。
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
