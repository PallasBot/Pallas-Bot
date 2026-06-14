# 多进程分片（生产部署）

单进程承载 **十余只及以上** 牛牛时，事件循环与连接池压力会明显上升。分片在 **共享同一 `data/` 目录** 的前提下，将集群拆为 **1 个 hub + 多个 worker**，对外仍是一个 Pallas-Bot 集群（WebUI、协议端管理、数据库配置统一）。

| 进程 | 入口 | 职责 |
|------|------|------|
| **hub** | `bot_hub.py` | WebUI、`pallas_protocol`、relogin、注册表、AI/MAA 回调入口；**不**接牛牛反向 WebSocket |
| **worker × N** | `bot_worker.py` | 每进程约 **5** 只牛牛（`PALLAS_SHARD_BOTS_PER`），运行 repeater、duel 等游戏逻辑插件 |

**适用场景**：生产环境多牛账号、希望降低单进程卡顿或便于按片扩容 worker。
**不适用**：仅 1～2 只牛、无性能瓶颈时，继续使用 `uv run nb run` 单进程即可。

### 插件加载（hub / worker）

| 角色 | 来源 |
|------|------|
| **unified** | 显式加载 **`ingress_gate`**（联邦 + 跨 Bot claim）+ 扫描 **`src/plugins/`**（跳过 `relogin_forward`、`maa_hub`、`pallas_console_metrics` 等分片专用项）+ **`pyproject.toml` 里额外的 `plugin_dirs`** + **`[tool.nonebot.plugins]`** + **`extra_plugin_dirs`** |
| **hub** | 代码白名单（WebUI、协议端、relogin 等）+ **`[tool.nonebot.plugins]`** 中的 pip 包（如 `nonebot-plugin-apscheduler`） |
| **worker** | 扫描 **`src/plugins/`**（跳过 webui / protocol / relogin）+ 显式加载 **`ingress_gate`** + **`pyproject.toml` 里额外的 `plugin_dirs`** + **`[tool.nonebot.plugins]`** |

从别处下载的插件：用 `nb plugin install` 或 `pip` 安装后，在 **`pyproject.toml`** 声明，例如：

```toml
[tool.nonebot]
plugin_dirs = ["src/plugins", "plugins"]   # plugins/ 为仓库外或自建目录

[tool.nonebot.plugins]
my-store-plugin = ["my_store_plugin"]      # pip 包对应的模块名
```

worker 会自动加载除 `src/plugins` 以外的 `plugin_dirs`、`pallas.toml` 的 **`extra_plugin_dirs`**（推荐 `local/plugins`）以及上表中的模块。详见 [站点定制与更新](site-customization-and-updates.md)。实现见 `src/platform/bot_runtime/plugin_loader.py`（`UNIFIED_SKIP_PLUGIN_NAMES` / `WORKER_SKIP_PLUGIN_NAMES`）。

部署入口见 [标准部署 · 多进程分片](../Deployment.md#多进程分片可选) 与 [Docker 部署 · 多进程分片](DockerDeployment.md#多进程分片可选)。

## 生产前提

- **共享 `data/`**：hub 与全部 worker 必须映射/挂载**同一路径**（`registry.json`、`coord/`、协议端 `accounts.json`、控制台数据等）。
- **端口规划**：hub 默认 **8088**；worker 从 **8090** 起连续或按注册表分配（见下文）。防火墙与安全组需放行 hub + 全部 worker 监听端口。
- **协议端 WS**：各牛牛账号的 `ws_url` 指向**所属 worker 端口**（创建账号或 `run_sharded_bot.sh start` 时会写注册表并同步协议端）。
- **数据库**：与单进程相同；使用 PostgreSQL 时注意 **`max_connections` ≥ worker 数 × `PG_POOL_SIZE`**（见 [PostgreSQL 连接池](#postgresql-连接池)）。
- **Pallas-Bot-AI**：回调 URL 固定打到 **hub**（`CALLBACK_PORT` / hub 的 `PORT`），勿指向 worker。

## 一键启动（推荐）

仓库根目录：

```bash
chmod +x scripts/run_sharded_bot.sh scripts/sync_shard_protocol_ports.py
./scripts/run_sharded_bot.sh start
./scripts/run_sharded_bot.sh status
./scripts/run_sharded_bot.sh stop
```

- 默认 **每片 5 牛**，按 `accounts.json` / 注册表自动计算 worker 数量（例如 22 个 enabled 账号约 **1 hub + 5 worker**，端口 8090～8094）。
- 强制 worker 数：`./scripts/run_sharded_bot.sh start --workers 5`
- 日志：`data/pallas_shard/logs/hub.log`、`worker-0.log` …（**当前会话**；每次 worker/hub 启动时非空旧文件会归档到 `logs/archive/`，默认每 stem 保留 8 份，可用 `PALLAS_SHARD_LOG_ROTATE_ON_START`、`PALLAS_SHARD_LOG_ARCHIVE_MAX` 调整）
- PID：`data/pallas_shard/run/*.pid`

`start` / `restart` 时脚本会：

1. **`restart`**：`stop` 后由 `wait_shard_worker_ports.py` 等待注册表中的 worker 端口可绑定（默认 60s，可用 `PALLAS_SHARD_PORT_RELEASE_TIMEOUT` 调整）。
2. **`shard_startup_ports.py`**：写回 `registry.json` 的 `shards[].port`，再同步协议端 `ws_url`（以落盘后的注册表为准）。
3. 协议端对齐规则：端口/路径须与注册表一致；主机名可不同（如 Docker `172.17.0.1` vs `127.0.0.1`）。有变更时需在协议端 **重启** 对应账号。

**均已对齐且端口空闲** 时，启动日志会标明跳过 registry / 协议端同步。
跳过协议端同步：`start --skip-port-sync`；不避让占用端口：`start --no-skip-occupied-ports`。

单独同步协议端（不启停进程）：

```bash
uv run python scripts/sync_shard_protocol_ports.py
uv run python scripts/sync_shard_protocol_ports.py --dry-run
```

### 进程守护

分片下 **仅对 hub 做 HTTP 探活** 不够覆盖 worker 断连。生产建议：

- 使用 **`run_sharded_bot.sh`** 统一管理启停；或
- 为 hub 与各 worker 分别配置 **systemd / supervisor**，并共享 `data/`；或
- 宿主机 `bot_watchdog.py` **仅监护 hub** 时须 **`--no-spawn`**，且 worker 由同一套编排保证拉起（见 [进程守护脚本](../Deployment.md#进程守护脚本)）。

## 配置与进程角色

运行配置以 **`config/pallas.toml`** + **`data/pallas_config/webui.json`** 为主（见 [配置存储](settings-storage.md)）；根目录 **`.env` 仅遗留只读合并**，WebUI 不再写入。分片编排仍可用 `run_sharded_bot.sh` 的 `env KEY=val` 注入 **`PALLAS_BOT_ROLE`、`PALLAS_SHARD_ID`、`PORT`** 等，**优先于磁盘同名项**。

### Hub / Worker 常用项

写在 `pallas.toml` 的 `[env]`（或 WebUI「通用配置」），或由启动脚本注入：

| 键 | Hub 示例 | Worker 示例 |
|----|----------|-------------|
| `PALLAS_SHARD_ENABLED` | `true` | `true` |
| `PALLAS_BOT_ROLE` | `hub` | `worker` |
| `PORT` / `PALLAS_SHARD_HUB_PORT` | `8088` | 见注册表 |
| `PALLAS_SHARD_WORKER_BASE_PORT` | `8090` | — |
| `PALLAS_SHARD_BOTS_PER` | `5` | — |
| `PALLAS_SHARD_WS_HOST` | `127.0.0.1` | — |
| `PALLAS_SHARD_ID` | — | `0`（worker-1 为 `1`…） |

`PALLAS_SHARD_WS_HOST`：写入注册表、供协议端连接的 worker 主机（Docker 内网或对外 IP 时改为实际可达地址）。worker 的 `PORT` 须与 `data/pallas_shard/registry.json` 中 `shards[].port` 一致。

### 跨进程 claim（需 Redis）

当前分片模式的跨进程 claim **依赖 Redis**。与 **Pallas-Bot-AI** 共用 Redis 时可直接复用；在 **`config/pallas.toml` 的 `[env]`** 中配置（勿再依赖根目录 `.env`）：

| 键 | 说明 |
|----|------|
| `REDIS_URL` / `PALLAS_COORD_REDIS_URL` | 与 AI 相同，如 `redis://127.0.0.1:6379/0` |
| `PALLAS_COORD_REDIS_ENABLED` | `auto`（默认）：可 ping 则启用；`true` 强制；`false` 禁用 |
| `PALLAS_COORD_REDIS_CLAIM_TTL_SEC` | claim 键 TTL，默认 86400 |
| `pallas:presence:bots` | （自动）worker 在线状态 HASH；Redis 不可用时仍用 `worker_presence.json` |

`./scripts/run_sharded_bot.sh start` 会读取 **`pallas.toml` / `webui.json`** 并调用 `detect_shard_redis.py` 自动探测；未配置、缺依赖或不可达时，分片 claim 将不可用，应先补齐 Redis 配置后再启动。

依赖：`uv sync --extra coord-redis`（或 `deploy-shard`，用于安装 `redis` 包）。

### 共享路径

| 项 | 说明 |
|----|------|
| **`config/pallas.toml`** | 各进程同一份（`[bootstrap]` 数据库与监听；插件项多在 `webui.json`） |
| **`data/`** | 必须同一路径；含 `pallas_shard/registry.json`、`coord/`、`accounts.json` 等 |

### Worker 端口

| 方式 | 说明 |
|------|------|
| **`.env`** | `PALLAS_SHARD_WORKER_BASE_PORT=8090` |
| **启动脚本** | `./scripts/run_sharded_bot.sh start --worker-base 8090` |
| **注册表** | `registry.json` 的 `worker_base_port` 与各 `shards[].port`（协议端以 **实际 `port`** 为准） |

默认 `start` 从起点向后扫描并**跳过已占用 TCP 端口**；单独写注册表：`uv run python scripts/apply_shard_worker_ports.py --workers 7 --base 8090`。

## 注册表

- 路径：`data/pallas_shard/registry.json`
- **顶层运行参数**（`bots_per_shard`、`worker_base_port`、`hub_port`、`ws_host` 等）在每次加载/保存注册表时会用 **`.env` / 进程环境** 覆盖，避免磁盘里残留的测试值（如 `bots_per_shard: 2`）影响生产。
- 新建协议端账号 / relogin「创建牛牛」时自动 `assign_bot_to_shard(qq)`，并写入该牛专属的 `ws_url`（**不会**进入 `test` 分片）；保存时会**裁剪**无账号的空分片行。
- 注册表异常膨胀时：`uv run python scripts/shard_registry_repair.py compact`；恢复生产 QQ 归属：`restore-production`（会备份当前文件）。
- 跨进程 **claim**（`data/*/message_claims`）与 worker **`ingress_gate`** 依赖共享 `data/`。

### 测试 worker（`registry.test`）

专用于用户自测：账号须**手动**迁入，不参与自动负载均衡。

```bash
./scripts/run_sharded_bot.sh test init
./scripts/run_sharded_bot.sh test add <QQ> --sync-ws
./scripts/run_sharded_bot.sh test start          # 仅启 worker-test
./scripts/run_sharded_bot.sh test status
./scripts/run_sharded_bot.sh test stop
```

也可使用快捷形式：`test-start`、`test-add <QQ>` 等（见 `./scripts/run_sharded_bot.sh -h`）。

注册表字段 `test`：`enabled`、`shard_id`（默认 99）、`port`（0 为自动选取）、`auto_assign`（固定 false）。环境变量：`PALLAS_SHARD_TEST_ID`、`PALLAS_SHARD_TEST_PORT`。

WebUI：`GET /pallas/api/shard-registry` 查看分片与 QQ 归属（需控制台 token）。日常运维仍只访问 **hub**：`http://<host>:8088/pallas/`。

## Docker

示例编排见仓库 [`docker-compose.shard.example.yml`](../../docker-compose.shard.example.yml)（hub + 多个 worker，**共用** `./pallas-bot/config/pallas.toml` 与 `./pallas-bot/data`）。

要点：

- hub：`APP_MODULE=bot_hub:app`，暴露 **8088**
- 每个 worker：`APP_MODULE=bot_worker:app`，`PALLAS_SHARD_ID` 与 `ports` 一一对应
- NapCat / 协议端在 Docker 模式下，`PALLAS_SHARD_WS_HOST` 或协议端插件中的 Docker OneBot 主机须能访问 **worker 容器端口**

完整步骤见 [Docker 部署 · 多进程分片](DockerDeployment.md#多进程分片可选)。

## 手动启动顺序

1. 启动 **hub**（`uv run python bot_hub.py` 或 `APP_MODULE=bot_hub:app`）
2. 按注册表启动 **worker 0..N**
3. 确认协议端各账号 WS 为 `ws://<host>:809x/onebot/v11/ws`（与注册表一致）
4. 协议端账号变更端口后 **重启** NapCat 实例

## 跨 worker 协调（共享 `data/pallas_shard/`）

| 能力 | Redis 键 / 模块 | 说明 |
|------|-------------|------|
| 牛牛报数顺序 | `pallas:coord:bot_count:*` | 各片登记 → 收集窗口 → 最小 QQ finalize 顺序 |
| 决斗 QTE 代答 | `pallas:duel_qte:session:*` + Pub/Sub | 主持片写会话，应答牛所在片 listener 回写 |
| 同群决斗互斥 | `pallas:coord:duel_group:*` | 跨片占用（`duel_group.py` 薄封装） |
| 同群独占活动 | `pallas:coord:<namespace>:*` | 通用 `group_activity`；如卧底 `spy_group` |
| 指定牛代发 API | `pallas:coord:bot_action:*` + Pub/Sub | 跨片请求 + listener |
| 复读近期语料 | `pallas:repeater_buffer` + Pub/Sub | ingress 获胜片广播并即时合并 |
| 群级短占位 | `pallas:coord:group_gate:*` | 含 `draw` owned gate |
| 在线态 / WebUI | `worker_presence.json` | hub 读各 worker 连接 |
| 控制台指标 | `stats/worker-{N}.json` | hub 合并展示 |
| registry / fleet | `registry.json` + mtime | `shard_data_sync` 失效缓存 |

worker 由 `src/platform/shard/coord/worker_poll.py` 启动 Redis listener，监听 `duel_qte`、`bot_action` 与 repeater 缓冲广播。

### 同群独占活动（`group_activity`）

适用于**同群同时只允许一场**的长时活动（开房、开战等），与短时 `group_gate` 占位不同。实现见 `src/platform/shard/coord/group_activity.py`；未分片时回退进程内 `local_busy`，无需 Redis。

| 能力 | API | 说明 |
|------|-----|------|
| 开闸（含孤儿锁回收） | `begin_group_exclusive_activity(namespace, group_id, has_local=..., local_alive=...)` | 插件侧入口：`src/platform.multi_bot.group` / `dedup` |
| 占锁 / 释锁 | `get_group_activity_lock(namespace).try_begin` / `.end` | Redis 键 `pallas:coord:<namespace>:{group_id}` |
| 局进行中 | `.mark_session` / `.clear_session` | 防止 worker 崩溃后误回收仍在进行的局 |

**本地 / pip 插件**不必在 `src/platform/shard/coord/` 新增 `*_group.py`；在插件内配置 namespace 即可。若需分片下 **主持牛 ingress 路由**，在 `PluginMetadata.extra` 增加 `hosted_activity_ingress`（见 `who_is_spy`）。

```python
from src.platform.multi_bot.dedup import begin_group_exclusive_activity
from src.platform.shard.coord.group_activity import get_group_activity_lock

gate = await begin_group_exclusive_activity("my_game", group_id, has_local=group_id in rooms)
if gate == "busy":
    return
lock = get_group_activity_lock("my_game")
lock.mark_session(group_id, session_active=True)  # 可选：局开始后
# ...
lock.end(group_id)
```

内置 **`duel`** 仍保留 `duel_group.py`（含 `session_pair` 与 `get_duel_pair` 孤儿回收）；新插件按上表自建 lock 配置即可。`coord_pending.py` 中的 `spy_group` 前缀仅用于可观测性键空间统计。

## WebUI 与日志（hub）

- `GET /pallas/api/bots`：读 **worker_presence.json**（hub 无反向 WS）。
- `GET /pallas/api/logs`：合并 `data/pallas_shard/logs/hub.log` 与各 `worker-*.log` 尾行（`sharded_logs: true`）。
- `GET /pallas/api/shard-observability`：合并各 worker `stats/worker-*.json` 的 **ingress 命中率**、**coord 积压**（实时统计 Redis 键空间）、**PG 连接池粗算**；**WebUI 首页**在分片模式下展示「分片可观测」面板。
- `./scripts/run_sharded_bot.sh status`：输出 **分片可观测** 摘要（同 API 数据源）。
- `uv run python scripts/shard_observability_snapshot.py`：完整 JSON；`scripts/shard_observability_status.py`：终端摘要。
- `plugin-run-stats` / `message-stats`：合并各 worker 的 `stats/worker-*.json`；ERROR 日志合并 worker/hub 落盘文件。
- 实时 SSE 以 **hub 本进程** 为主；查全集群历史建议日志页轮询。

## AI 与 MAA 回调

- **Pallas-Bot-AI**：`http://<hub>:<PORT>/callback/{request_id}`；任务登记在 worker，hub `callback` 插件转发到对应 worker。
- **牛牛画画**、**MAA 远控**：不走 AI callback；MAA 客户端轮询 hub，`maa_hub` 按 QQ 转发至登记 worker；`maa_public_base_url` 填 **hub 对外基址**。

## PostgreSQL 连接池

同一 worker 上多只牛会各收到群消息；未抢到 ingress 的会话可能伴随 `asyncio.CancelledError`。若出现 **non-checked-in connection**，多为预处理器被取消时连接未归还（代码侧已 `shield` / `invalidate` 兜底）。

生产请估算：**(worker + hub) 进程数 × (`PG_POOL_SIZE` + `PG_MAX_OVERFLOW`) < PostgreSQL `max_connections`**，并预留其他应用连接。分片下常见配置为每进程 `12+8`（峰值约 20/进程）；勿将单进程 `pool+overflow` 设为数百，否则多 worker 会打满数据库。

启动后若配置过大，日志与 `GET /pallas/api/shard-observability` 的 `pg_pool.warning` 会提示。

## 多 Bot 同群行为摘要

- **`ingress_gate`**（unified / worker）：fleet、@ 定向、ingress claim、greeting/报数 fanout。
- **fanout 白名单**：WebUI「入站：全员同响口令」或 `PALLAS_INGRESS_FANOUT_GREETING`；**`牛牛报数` / `牛牛出列` 恒 fanout**；**喝酒/醒酒口令**（`牛牛喝酒` 等）见 `drink_plaintext` 恒 fanout。**做梦/醒梦口令不走 fanout**：经 ingress 跨牛 claim 仅一只牛开梦；做梦中由 **`dream_host_gate`**（`bind_group_owned_gate`）绑定主持牛，ingress 与采集/醒梦 matcher 仅主持牛通过。
- **接话 / 主动发言**：ingress 为 **shard 级 claim**（每条消息一个 worker 片通过，该片上各牛可进 matcher）；复读由**本片代表牛**（最小 QQ）统一学习与接话判定；**近期群消息**经 `coord/repeater_buffer/`（可选 Redis Pub/Sub）同步到各 worker 内存；**learn 上下文**在内存链不足时回退 `MessageRepository.find_recent_in_group`；fanout 仅在群内 **≥2 只可复读在线牛** 时启用（与单进程一致），跨片经 `bot_action` 批量代发。主动发言定时任务仅代表牛 worker 执行。
- **`dream` 跨群漂流**：各 worker 本地 `_dream_active` 仅本进程；分片下经 `coord/dream_drift`（Redis 登记做梦群 + `pallas:dream_drift` pub/sub）把梦话投到其它 worker 上同牛号的做梦群；**同群多牛仅主持牛执行做梦**（开梦 claim + owned gate），与喝酒等各牛独立 fanout 不同。
- **`duel` / 八角笼**：跨片 `coord/duel_group`、`bot_action`、`duel_qte`。
- **同群独占类插件**（如 **`who_is_spy`**）：`group_activity` + `begin_group_exclusive_activity`；在 `PluginMetadata.extra["hosted_activity_ingress"]` 声明 `plugin_key`、`activity_namespace`、口令前缀等，ingress 经通用 **`hosted_activity_ingress_passes`**（`src/platform/ingress/hosted_activity_gate.py`）按 **owned gate 主持牛** 路由局内口令与述词（**非 fanout**）。开/结束类口令可列在 `always_pass_prefixes` 始终放行。实现见 `src/platform/shard/coord/hosted_activity_coord.py`；卧底仍保留 `spy_activity.py` 供 prep 元数据读写。
- **`repeater`**：忽略全 fleet QQ；**`bot_status`**：建议 `bot_status_list_mode=auto`。

与单进程 `multi_bot_group` 文件 claim 机制同源；分片 worker 额外保留 ingress 预处理器，避免未改造插件在多 worker 下重复响应。

## Hub 排障

| 现象 | 处理 |
|------|------|
| `buildInfo requires authentication` | 配齐 `MONGO_*` 或 `DB_BACKEND=postgresql` + `PG_*`；PG 需 `uv sync --extra pg` |
| 牛牛连不上 / WS 错误 | 核对 `registry.json` 与协议端 `ws_url`、worker 是否已启动；执行 `sync_shard_protocol_ports.py` 后重启协议端账号 |
| 仅 hub 正常、群无响应 | 检查对应 worker 日志与 `worker_presence.json` |

## 架构约束（部署前知晓）

- worker **不**加载 `pallas_webui` / `pallas_protocol` / `relogin_bot`。
- hub **不**加载主要游戏插件；须 worker 承载牛牛逻辑（hub 加载 **`callback`** 用于 AI 转发）。
- WebUI 插件目录展示仓库全集并标注 `load_role`；worker 专属配置在 hub 可预览，**保存后需 worker 重启或热重载**。
- `learn_queue_max_size` 等按 **单 worker 进程** 生效。
- 从单进程迁到分片：先备份 `data/`，用 `run_sharded_bot.sh start` 分配端口并同步协议端，再逐账号重启 NapCat。

## 附录：本地共用数据测试

仅开发/验证时使用，勿在生产直接套用：

```bash
./scripts/shard_test_enter.sh          # 可 --main-repo 指定主仓
uv sync --extra pg                   # 与主仓 DB 一致时
./scripts/run_sharded_bot.sh start
./scripts/run_sharded_bot.sh stop
./scripts/shard_test_leave.sh
```

状态在 `.shard_test_state/`（勿提交）。仅共用数据、不改端口：`shard_test_enter.sh --skip-port-migrate`。
