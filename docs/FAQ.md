# 常见问题（FAQ）

> 导航：[`README`](../README.md) · [`标准部署`](Deployment.md) · [`Docker 部署`](DockerDeployment.md)

本页收录 `Pallas-Bot` 的常见问题与排查建议。
若你是首次部署，建议先阅读 `README.md` 中的「快速开始」；控制台与协议端管理页的口令说明、遗忘后的重置方式见本页「部署排障」。

## 学习机制

### Q: 牛牛为什么会说群里没出现过的话？

A: 因为有跨群机制。超过阈值的相似表达会沉淀为全局语料。

### Q: 为什么有时像在回复“命令”？

A: 可能是从其他机器人或其他群消息学习到的。

### Q: 怎么教牛牛说一句固定的话？

A: 可以通过重复训练强化，例如：

```text
—— 牛牛你好
—— 你好呀
—— 牛牛你好
—— 你好呀
—— 牛牛你好
—— 你好呀
```

## 使用与管理

### Q: 牛牛说了不合适的话怎么处理？

A: 群管理员或者牛牛管理员可以回复该消息发送“不可以”，或直接撤回。多群共同禁用后，会形成全局禁用。

### Q: 没人说话时，为什么牛牛会突然发言？

A: 这是主动发言功能，内容同样来源于学习到的群聊语料。

### Q: 管理员、牛牛管理员、号主、超管都是什么?

A: **群管理员**指 QQ 群里的管理员。**牛牛管理员**（数据库里的 **`admins`**）是可以控制该牛牛部分能力的人（例如私聊「牛牛重新上号」）；一般应把**号主** QQ 配进 **`admins`**，便于号主控制自己的牛牛。**超管**即 `.env` 里 **`SUPERUSERS`**，对所有牛牛有最高权限。

给牛牛增加/修改 **`admins`** 的方式见下文 [如何为牛牛添加管理员（`admins`）](#faq-bot-admins)。

<a id="faq-bot-admins"></a>

### Q: 如何为牛牛添加管理员（`admins`）？

A: **`account`** 为该牛牛的 QQ 号；**`admins`** 为 **QQ 号组成的 JSON 数组**（整数）。**不能**在 `.env` 里配置；改库或改 Web 控制台里的数据后，权限会按 `BotConfig` 缓存规则生效（Mongo 侧文档缓存约 60 秒），未立刻生效时可稍等或重启 Bot。

**新建牛牛时（自动写入 `admins`）**：由 **超管** 私聊发送 **「创建牛牛」**（插件 `relogin_bot`），在命令参数中带上 **号主 QQ**（可填多个）；插件在协议端创建账号并启动后，会把这些号主 **自动写入**该牛牛的 **`admins`**，通常不必再手动改库或进 Web「数据库管理」补一行。命令格式与流程见 [relogin_bot 说明](plugins/relogin_bot/README.md)。

**方式一：Web 控制台（推荐，与前端「数据库管理」联动）**

1. 浏览器登录 Pallas Web 控制台（路径前缀见 `pallas_webui` 的 `PALLAS_WEBUI_HTTP_BASE`，常见为 `/pallas/`）。
2. 打开侧边栏 **「数据库管理」**（前端路由 `database`，完整路径形如 **`/pallas/database`**，随 HTTP 基路径变化）。
3. 在表类型中选择 **`config (bot_config)`**，找到 **`account`** 等于目标牛牛 QQ 的行。
4. 编辑 **`admins`** 为 JSON 数组（例如 `[123456789, 987654321]`）并保存。

**方式二：MongoDB（`DB_BACKEND=mongodb`）**

- 集合名：**`config`**（对应代码中的 `BotConfigModule`）。
- 文档字段：**`account`**（牛牛 QQ，数值）、**`admins`**（QQ 号数组）。
- 库名：与当前 Bot 使用的 Mongo **数据库名**一致（见 `.env` 中 **`MONGO_DB`** / 连接串说明）。

在 **`mongosh`** 中示例（将数字换成实际 QQ）：

```javascript
db.config.updateOne(
  { account: 3888888888 },
  { $set: { admins: [2777777777, 2666666666] } }
)
```

若该 `account` 尚无文档，需先有 Bot 运行产生的配置或自行插入完整结构；一般已有行时只更新 **`admins`** 即可。

**方式三：PostgreSQL（`DB_BACKEND=postgresql`）**

- 表名：**`bot_config`**。
- 主键列：**`account`**（`bigint`，牛牛 QQ）。
- **`admins`**：`jsonb`，内容为 JSON 数组。

```sql
UPDATE bot_config
SET admins = '[2777777777, 2666666666]'::jsonb
WHERE account = 3888888888;
```

命令行工具也可使用仓库提供的 [`tools/config/config.mongodb`](../tools/config/config.mongodb) 等脚本（若你环境已配置好）；与直接改库等价，择一即可。

## 部署排障

### Q: 启动后不回复，应该先查什么？

A: 先检查数据库连通性、`OneBot WebSocket` 是否已连上（Docker 默认 Compose 无独立 NapCat，需在 **`/protocol/console/`** 协议端管理里创建实例并配置 WS）、`.env` 是否生效，再看控制台是否有持续报错。

### Q: 控制台 / 协议端管理页的口令在哪里配？

A: 不再从 `.env` 读取口令。首次启动在日志里打印随机口令，哈希保存在 `data/pallas_console/auth_state.json`；浏览器访问 `/pallas/login` 或协议端登录页登录。仅本机开发可在 `pallas_webui` 配置中开启 `pallas_webui_dev_mode` 跳过控制台鉴权。

### Q: 遗忘了控制台 / 协议端管理页的登录口令怎么办？

A: 磁盘上只有哈希，**没有「忘记密码」邮件或在线找回**；需能访问 Bot 的数据目录或历史日志。

- **从未在设置里改过口令**：可看同目录下的 **`data/pallas_console/default_login_password.txt`**（若仍存在）。
- **仍保留首次启动时的终端 / 容器日志**：其中会有「Pallas 默认口令」一类输出。
- **以上都没有**：停掉 Bot，删除或移走 **`data/pallas_console/auth_state.json`** 后重启；进程会重新生成随机口令并写入日志（必要时可一并删除 **`session_secret.bin`**，避免旧会话状态干扰）。**所有已登录会话会失效**，新口令请妥善保存。

### Q: 执行 `docker compose` 时报 `project name must not be empty` 怎么办？

A: Compose 默认用**当前文件夹名**作为项目名；目录名为中文等时，部分 Docker Desktop 会推出空项目名从而报错。处理方式：

- 使用本仓库最新的 [`docker-compose.yml`](../docker-compose.yml)，其中已设置顶层 **`name: pallas-bot`**。
- 或启动时显式指定项目名：`docker compose -p pallas-bot up -d`（带 profile 时同理写在 `--profile` 前即可）。
- PowerShell 也可先执行：`$env:COMPOSE_PROJECT_NAME = "pallas-bot"`。

同一台机器多套实例请使用不同项目名（如 `-p pallas-home2`），避免网络与资源名冲突。更多说明见 [Docker 部署](DockerDeployment.md) 文档中的「排障」一节。

### Q: Postgres 容器日志里 `FATAL: database "PallasBot" does not exist` 是什么问题？

A: 表示 **Postgres 里没有叫 `PallasBot` 的库**，而 Bot 的 **`PG_DB`**（默认）正在连它。常见情况是 **`./postgres/data` 卷以前用别的 `POSTGRES_DB` 初始化过**，改配置后不会自动建新库。可对齐 **`PG_DB`** 与已有库名、**删卷重建**（会丢数据）或进容器 **`CREATE DATABASE`**。详见 [Docker 部署](DockerDeployment.md) 排障。

### Q: Docker 里日志写「连接 MongoDB 127.0.0.1:27017」对吗？

A: **在容器里 `127.0.0.1` 只指向容器自己**，连不到 Compose 里的 **`mongodb` / `postgres` 服务**。本仓库 [`docker-compose.yml`](../docker-compose.yml) 已注入 **`MONGO_HOST=mongodb`**、**`MONGO_PORT=27017`**，并在用内置 PG 时注入 **`PG_HOST=postgres`**、**`PG_PORT=5432`**（与 **service 名**一致），覆盖挂载 `.env` 里的本机地址；若仍看到 `127.0.0.1`，多半是**旧 compose 未更新**或**自建编排未设置**。外置数据库时请删改 compose 里对应项并在 `.env` 写明真实地址。详见 [Docker 部署](DockerDeployment.md)。

### Q: Docker 里 `help` 报「样式路径不存在 `/app/resource/styles/default`」？

A: 常见原因是 **volume 把整个 `/app/resource` 挂成宿主机目录**，而宿主机上没有 **`resource/styles/default`**，盖住了镜像里自带的 help 样式。请把 compose 改为**只挂载** **`./pallas-bot/resource/voices:/app/resource/voices`**（与仓库 [`docker-compose.yml`](../docker-compose.yml) 一致），或在宿主机 `resource` 下补全 **`styles/default`**。详见 [Docker 部署](DockerDeployment.md) 排障。

### Q: 本地 `docker build` 拉 `python:3.12-slim` 报 `registry-1.docker.io` / `EOF`？

A: 多为 **Docker Hub 访问不稳定**（国内常见）。可在仓库根目录使用带 **`BASE_IMAGE`** 的镜像前缀构建，例如：`docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .`（以你当前能访问的镜像站为准）；或为 Docker 配置 **registry-mirrors** / 代理。详见 [Docker 部署](DockerDeployment.md) 排障。

### Q: Docker Compose 起内置 Postgres 时，还要不要在 compose 里再配一套 `POSTGRES_USER`？

A: **不用。** 仓库 [`docker-compose.yml`](../docker-compose.yml) 已用 **`PG_USER` / `PG_PASSWORD` / `PG_DB`** 插值生成 **`POSTGRES_*`**。你只需在 **`pallas-bot/.env`** 里维护 **`PG_*`**（与 Bot 进程读的是同一份），启动时带上 **`docker compose --env-file ./pallas-bot/.env --profile postgres up -d`**，让 Compose 能读到这些变量；否则插值会回落到 compose 里写的默认值，可能与 Bot 实际使用的账号不一致。

### Q: Docker 启动报错里提到 `mounting`、`.env`、`not a directory` 或 `directory onto file` 是什么情况？

A: Compose 把宿主机 **`./pallas-bot/.env`** 挂到容器 **`/app/.env`**，两边都必须是**同一个文件**。若宿主机上 `.env` 被建成了**文件夹**（例如在还没有 `.env` 文件时就启动过，或手动建错），就会报这类错。请删除宿主机上错误的 **`pallas-bot/.env` 目录**，从仓库复制 [`.env`](../.env) 为**文件**放到该路径，再重新 `docker compose up`。详见 [Docker 部署](DockerDeployment.md) 中「排障」与配置步骤里的说明。

### Q: 协议端管理里反向 WebSocket 要不要写成「主机为 `pallasbot`」？和 Compose 的 `pallasbot` 是什么关系？

A: **`pallasbot` 只是 Compose 服务名**，DNS 只在**同一 Compose 网络里的容器**之间有效。协议端在 **Linux Docker 模式**下用 `docker run` 起的 NapCat **默认不在**该网络里；若把客户端地址写成 **`ws://pallasbot:<PORT>/onebot/v11/ws`**（明文 WebSocket、主机填服务名），在默认桥接场景下**往往连不上**。插件会把 **主机** 改成解析后的 **`PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`**（留空时 Linux **`bridge`** 多为**默认网关 IP** 或 **`172.17.0.1`**；**`host` 网络为 `127.0.0.1`**）再写入 **`onebot*.json`**，**不会**自动替你填 `pallasbot`。一般不必为此去「取消」Compose 自定义网络；只有当你**自行**把 NapCat 做成与 Bot **同一 Compose 网络**的 service 时，才适合继续用 **`ws://pallasbot:<PORT>/onebot/v11/ws`** 这类内网写法。详见 [Docker 部署](DockerDeployment.md) 与 [`pallas_protocol` 插件说明](plugins/pallas_protocol/README.md) 中「Docker 与反向 WebSocket」一节。
