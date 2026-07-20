# 常见问题

按标题或关键词检索。部署与启动类问题见下文「部署排障」；运行时顺序见 [排障](/maintainer/operate/troubleshooting)。

## 问题分类

```mermaid
flowchart TD
  Start[故障] --> Boot{启动失败或页面打不开?}
  Boot -->|是| Dep[部署与配置 · FAQ 后半 / 排障]
  Boot -->|否| QQ{QQ在线但群不回?}
  QQ -->|是| Proto[连接协议端 · connect-qq]
  QQ -->|否| AI{闲聊或记忆不生效?}
  AI -->|是| Llm[运维 LLM 与 AI]
  AI -->|否| Learn{语料或说话奇怪?}
  Learn -->|是| LearnSec[学习机制]
  Learn -->|否| Admin[使用与管理]
```

## 学习机制

### Q: 牛牛为什么会说群里没出现过的话？

A: 有跨群机制。超过阈值的相似表达会沉淀成全局语料，别的群也可能用上。

### Q: 为什么有时像在回复「命令」？

A: 可能是从其他机器人、或其他群的消息里学到的。

### Q: 怎么教牛牛说一句固定的话？

A: 重复训练即可，例如：

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

A: 群管或**号主**（`admins` 里的 QQ）回复那条消息发「不可以」，或直接撤回。多群一起禁用后，会变成全局禁用。

### Q: 没人说话时，为什么牛牛会突然发言？

A: 主动发言功能。内容同样来自学到的群聊语料。

### Q: 管理员、号主、超管都是什么?

A: 见专页 **[号主](/guide/bot-owner)**（含三种角色对照与配置步骤）。摘要：

| 角色 | 是谁 |
| --- | --- |
| **群管理员** | QQ 群里的管理员 |
| **号主** | 该牛数据库 **`admins`** 里的 QQ |
| **超管** | `pallas.toml` 的 **`[bootstrap] superusers`** |

<a id="faq-bot-admins"></a>

### Q: 如何为牛牛配置号主（`admins`）？

A: 推荐在控制台 **实例与连接** 初始化 / 编辑，或超管私聊 `牛牛添加号主 …`。步骤、示例与其它方式见 **[号主](/guide/bot-owner#怎么配置)**。

**方式四：MongoDB（`DB_BACKEND=mongodb`）**（控制台不便时）

- 集合名：**`config`**（对应代码中的 `BotConfigModule`）。
- 文档字段：**`account`**（牛牛 QQ，数值）、**`admins`**（QQ 号数组）。
- 库名：与当前 Bot 使用的 Mongo **数据库名**一致（见 `config/pallas.toml` 的 **`[bootstrap.mongo] db`** 或连接串说明）。

在 **`mongosh`** 中示例（将数字换成实际 QQ）：

```javascript
db.config.updateOne(
  { account: 3888888888 },
  { $set: { admins: [2777777777, 2666666666] } }
)
```

若该 `account` 尚无文档，可在 Web「实例与连接」用 **初始化配置** 创建，或自行插入完整结构。

**方式五：PostgreSQL（`DB_BACKEND=postgresql`）**

- 表名：**`bot_config`**。
- 主键列：**`account`**（`bigint`，牛牛 QQ）。
- **`admins`**：`jsonb`，内容为 JSON 数组。

```sql
UPDATE bot_config
SET admins = '[2777777777, 2666666666]'::jsonb
WHERE account = 3888888888;
```

也可在 WebUI「数据库」页直接编辑 `bot_config` 表。

### Q: 如何备份 MongoDB / PostgreSQL？

A: **WebUI「数据库」页**有「数据库备份」面板；若未检测到 `mongodump` / `pg_dump`，页面会给出官方下载链接。也可在仓库根执行：`uv run python tools/scripts/backup_database.py`（按当前 `db_backend`），PostgreSQL 专用：`tools/scripts/backup_pg.py` 或 `sh tools/scripts/backup.sh -p`。

## 更新与版本

### Q: Docker 和 git clone，更新方式有啥区别？

A: **Docker**：代码在镜像里，更新主要是 **`docker compose pull`** 后重建容器，一般没有本机 git 冲突；数据与配置应在卷（`data/`、`config/pallas.toml` 等）里。**git clone**：更新是 **`git pull`**（或控制台「Bot 更新」在检测到 git 工作副本时的等价操作）；若你改过与上游同一已跟踪文件，可能冲突，需本地处理后再拉。详见 [标准部署 - 后续更新](/deploy/deployment) 与 [Docker 部署](/deploy/docker)。

### Q: `git pull --autostash` 能避免所有冲突吗？

A: **不能。**它只缓解「有未提交改动时 checkout/merge 被挡住」的情况；**双方改了同一行**等仍会产生冲突标记，必须人工解决。脚本或定时任务若需无人值守，更稳妥的是使用 **`git pull --ff-only`**，失败即停止并告警，而不是强行合并。

### Q: 控制台「版本与更新」里 Bot 一键更新失败，提示不是 git 工作副本？

A: 典型于 **Docker 镜像内运行**：容器里没有完整 `.git` 目录，更新页会显示 **`deployment_mode: docker`**，请用 **镜像拉取** 更新 Bot。若在 clone 目录运行仍失败，请根据返回的 **HTTP 详情原文**（或日志）排查：`git fetch` 网络、`fetch` 后仍无对应标签、**stash pop 冲突**，或 **非快进**（开发路径使用 `pull --ff-only`）等。

### Q: 怎样减少以后 `git pull` 跟上游冲突？

A: 尽量**不要**在仓库里直接改已跟踪源码；自定义用 **`config/pallas.toml`**、**`data/`**（含 WebUI 的 `webui.json`）、**`local/plugins/`**（`extra_plugin_dirs`）以及文档允许的挂载路径。若必须改源码，建议 **fork** 后维护自己的分支。详见 [升级与站点定制](/maintainer/deploy/upgrade)。

### Q: 控制台更新页显示的 deployment_mode 是什么？

A: **`docker`**：请用镜像更新；**`release_tag`** / **`release_tag_dirty`** / **`dev_clone`**：分别表示发布 tag 干净目录、tag 上有本地改动、开发分支克隆；后三者可用 WebUI git 更新（dirty 时会自动 stash）。见 [升级与站点定制](/maintainer/deploy/upgrade)。

## 部署排障

### Q: 启动后不回复查什么？

A: 数据库连通性；`OneBot WebSocket` 是否已连上（Docker 默认 Compose 无独立 NapCat，需在 **`/pallas/protocol`** 创建实例并配置 WS）；`config/pallas.toml` 与 `data/pallas_config/webui.json` 是否生效；控制台是否有持续报错。

### Q: 控制台 / 协议端管理页的口令在哪里配？

A: 不再从 `.env` 读取口令。首次启动在日志里打印随机口令，哈希保存在 `data/pallas_console/auth_state.json`；浏览器访问 `/pallas/login` 或协议端登录页登录。仅本机开发可在 `pallas_webui` 配置中开启 `pallas_webui_dev_mode` 跳过控制台鉴权。

### Q: 遗忘了控制台 / 协议端管理页的登录口令怎么办？

A: 磁盘上只有哈希，**没有「忘记密码」邮件或在线找回**；需能访问 Bot 的数据目录或历史日志。

- **从未在设置里改过口令**：可看同目录下的 **`data/pallas_console/default_login_password.txt`**（若仍存在）。
- **仍保留首次启动时的终端 / 容器日志**：其中会有「Pallas-Bot 默认口令」一类输出。
- **以上都没有**：停掉 Bot，删除或移走 **`data/pallas_console/auth_state.json`** 后重启；进程会重新生成随机口令并写入日志（必要时可一并删除 **`session_secret.bin`**，避免旧会话状态干扰）。**所有已登录会话会失效**，新口令请妥善保存。

### Q: 执行 `docker compose` 时报 `project name must not be empty` 怎么办？

A: Compose 默认用**当前文件夹名**作为项目名；目录名为中文等时，部分 Docker Desktop 会推出空项目名从而报错。处理方式：

- 使用本仓库最新的 [`docker-compose.yml`](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.yml)，其中已设置顶层 **`name: pallas-bot`**。
- 或启动时显式指定项目名：`docker compose -p pallas-bot up -d`（带 profile 时同理写在 `--profile` 前即可）。
- PowerShell 也可先执行：`$env:COMPOSE_PROJECT_NAME = "pallas-bot"`。

同一台机器多套实例请使用不同项目名（如 `-p pallas-home2`），避免网络与资源名冲突。更多说明见 [Docker 部署](/deploy/docker) 文档中的「排障」一节。

### Q: Postgres 容器日志里 `FATAL: database "PallasBot" does not exist` 是什么问题？

A: 表示 **Postgres 里没有叫 `PallasBot` 的库**，而 Bot 的 **`PG_DB`**（默认）正在连它。常见情况是 **`./postgres/data` 卷以前用别的 `POSTGRES_DB` 初始化过**，改配置后不会自动建新库。可对齐 **`PG_DB`** 与已有库名、**删卷重建**（会丢数据）或进容器 **`CREATE DATABASE`**。本地也可设 **`PG_AUTO_CREATE_DB=true`**（需 `CREATEDB`）。详见 [Docker 部署](/deploy/docker)、[deploy/pg/README.md](https://github.com/PallasBot/Pallas-Bot/blob/main/deploy/pg/README.md)。

### Q: PostgreSQL 是否一定要用超级用户 / 管理员账号？

A: **不必。** 4.0 默认路径只连目标库做建表与迁移；`pg_stat_statements` 在独立事务里尝试启用，失败只降级诊断。Compose 用 `POSTGRES_DB` 建好库即可。托管 PG 请先建空库再填连接信息；可选扩展见 `deploy/pg/extensions.sql`。对应需求：[Issue #222](https://github.com/PallasBot/Pallas-Bot/issues/222)。

### Q: Docker 里日志写「连接 MongoDB 127.0.0.1:27017」对吗？

A: **在容器里 `127.0.0.1` 只指向容器自己**，连不到 Compose 里的 **`mongodb` / `postgres` 服务**。本仓库 [`docker-compose.yml`](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.yml) 已注入 **`MONGO_HOST=mongodb`**、**`MONGO_PORT=27017`**，并在用内置 PG 时注入 **`PG_HOST=postgres`**、**`PG_PORT=5432`**（与 **service 名**一致），覆盖 `pallas.toml` 里写的本机地址；若仍看到 `127.0.0.1`，多半是**旧 compose 未更新**或**自建编排未设置**。外置数据库时请删改 compose 里对应项并在 `pallas.toml` 写明真实地址。详见 [Docker 部署](/deploy/docker)。

### Q: Docker 里 `help` 报「样式路径不存在 `/app/resource/styles/default`」？

A: 常见原因是 **volume 把整个 `/app/resource` 挂成宿主机目录**，而宿主机上没有 **`resource/styles/default`**，盖住了镜像里自带的 help 样式。请把 compose 改为**只挂载** **`./pallas-bot/resource/voices:/app/resource/voices`**（与仓库 [`docker-compose.yml`](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.yml) 一致），或在宿主机 `resource` 下补全 **`styles/default`**。详见 [Docker 部署](/deploy/docker) 排障。

### Q: 本地 `docker build` 拉 `python:3.12-slim` 报 `registry-1.docker.io` / `EOF`？

A: 多为 **Docker Hub 访问不稳定**（国内常见）。可在仓库根目录使用带 **`BASE_IMAGE`** 的镜像前缀构建，例如：`docker build --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim -t pallasbot:local .`（以你当前能访问的镜像站为准）；或为 Docker 配置 **registry-mirrors** / 代理。详见 [Docker 部署](/deploy/docker) 排障。

### Q: Docker Compose 起内置 Postgres 时，还要不要在 compose 里再配一套 `POSTGRES_USER`？

A: **不用。** 仓库 [`docker-compose.yml`](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.yml) 已用 **`PG_USER` / `PG_PASSWORD` / `PG_DB`** 插值生成 **`POSTGRES_*`**。你只需在 **`pallas-bot/config/compose.env`**（由 [`config/compose.env.example`](https://github.com/PallasBot/Pallas-Bot/tree/main/config/compose.env.example) 复制）里维护 **`PG_*`**，并与 **`pallas.toml`** 的 `[bootstrap.postgres]` 一致；启动时带上 **`docker compose --env-file ./pallas-bot/config/compose.env --profile postgres up -d`**。否则插值会回落到 compose 默认值，可能与 Bot 实际使用的账号不一致。

### Q: Docker 启动报错里提到 `mounting`、`pallas.toml`、`not a directory` 或 `directory onto file` 是什么情况？

A: Compose 把宿主机 **`./pallas-bot/config/pallas.toml`** 挂到容器 **`/app/config/pallas.toml`**，两边都必须是**同一个文件**。若宿主机上该路径被建成了**文件夹**（例如在还没有配置文件时就启动过，或手动建错），就会报这类错。请删除错误目录，从仓库复制 [`config/pallas.example.toml`](https://github.com/PallasBot/Pallas-Bot/tree/main/config/pallas.example.toml) 为**文件**放到该路径，再重新 `docker compose up`。详见 [Docker 部署](/deploy/docker) 中「排障」与配置步骤里的说明。

### Q: 协议端管理里反向 WebSocket 要不要写成「主机为 `pallasbot`」？和 Compose 的 `pallasbot` 是什么关系？

A: **`pallasbot` 只是 Compose 服务名**，DNS 只在**同一 Compose 网络里的容器**之间有效。协议端在 **Linux Docker 模式**下用 `docker run` 起的 NapCat **默认不在**该网络里；若把客户端地址写成 **`ws://pallasbot:<PORT>/onebot/v11/ws`**（明文 WebSocket、主机填服务名），在默认桥接场景下**往往连不上**。插件会把 **主机** 改成解析后的 **`PALLAS_PROTOCOL_DOCKER_ONEBOT_HOST`**（留空时 Linux **`bridge`** 多为**默认网关 IP** 或 **`172.17.0.1`**；**`host` 网络为 `127.0.0.1`**）再写入 **`onebot*.json`**，**不会**自动替你填 `pallasbot`。一般不必为此去「取消」Compose 自定义网络；只有当你**自行**把 NapCat 做成与 Bot **同一 Compose 网络**的 service 时，才适合继续用 **`ws://pallasbot:<PORT>/onebot/v11/ws`** 这类内网写法。详见 [Docker 部署](/deploy/docker) 与 [`pb_protocol` 插件说明](/plugins/pb_protocol) 中「Docker 与反向 WebSocket」一节。

## 4.0 布局与迁移

<a id="faq-40-layout"></a>

### Q: 「媒体服务 / AI Runtime」显示不可达，聊天也不能配了吗？

A: **不能混为一谈。** 默认 LLM 聊天走 Bot 内核 Provider，在 **AI 配置 → 接入** 测通并保存即可，**不要求** `:9099` 可达。媒体服务红灯只影响唱歌/TTS 等，以及显式 `LLM_RUNTIME=ai_service` 的遗留路径。排障见 [LLM 与 AI](/maintainer/operate/llm-and-ai)。

### Q: 3.x 的 `src/plugins` 插件在 4.0 还能用吗？

A: **不能沿用旧路径。** 4.0 已移除 `src/` 目录；内置玩法迁至 **`packages/`** 与 **`pallas-plugin-*` 官方插件**，社区插件应使用 **`pallas.api.*`** 与 **`packages/<name>/` 或 `local/plugins/`** 布局。从 3.x 升级请读 [4.0 迁移指南](/guide/4.0-migration)。

### Q: 社区作者如何只依赖内核、不克隆整仓？

A: 使用 PyPI 包 **`pallas-core`**（也可本地构建 wheel：`./scripts/build_core.sh`），在扩展 `pyproject.toml` 声明 `pallas-core>=4.0.0,<5.0.0`，业务代码只 `import pallas.api.*`。示例见 [pallas.api Cookbook](/developer/plugin-development/pallas-api-cookbook) 与 `templates/pallas-plugin-extension/`。

### Q: WebUI 首次登录为什么要走 Setup Wizard？

A: 默认口令仅用于首次启动；改密后 `setup_state.json` 标记完成，路由守卫才放行其它页面。向导还推荐配置**协议端**与**插件扩展**；**AI 体检**仅在需要智能对话时可选配置。详见 WebUI「首次 Setup Wizard」页。
