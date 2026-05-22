# 多进程分片（生产部署）

单进程承载 **十余只及以上** 牛牛时，事件循环与连接池压力会明显上升。分片在 **共享同一 `data/` 目录** 的前提下，将集群拆为 **1 个 hub + 多个 worker**，对外仍是一个 Pallas-Bot 集群（WebUI、协议端管理、数据库配置统一）。

| 进程 | 入口 | 职责 |
|------|------|------|
| **hub** | `bot_hub.py` | WebUI、`pallas_protocol`、relogin、注册表、AI/MAA 回调入口；**不**接牛牛反向 WebSocket |
| **worker × N** | `bot_worker.py` | 每进程约 **5** 只牛牛（`PALLAS_SHARD_BOTS_PER`），运行 repeater、duel 等游戏逻辑插件 |

**适用场景**：生产环境多牛账号、希望降低单进程卡顿或便于按片扩容 worker。
**不适用**：仅 1～2 只牛、无性能瓶颈时，继续使用 `uv run nb run` 单进程即可。

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
- 日志：`data/pallas_shard/logs/hub.log`、`worker-0.log` …
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

## 环境变量

### Hub（`.env` 或编排注入）

```env
PALLAS_SHARD_ENABLED=true
PALLAS_BOT_ROLE=hub
PORT=8088
PALLAS_SHARD_HUB_PORT=8088
PALLAS_SHARD_WORKER_BASE_PORT=8090
PALLAS_SHARD_BOTS_PER=5
PALLAS_SHARD_WS_HOST=127.0.0.1
```

`PALLAS_SHARD_WS_HOST`：写入注册表、供协议端连接的 worker 主机（Docker 内网或对外 IP 时改为实际可达地址）。

### Worker

```env
PALLAS_SHARD_ENABLED=true
PALLAS_BOT_ROLE=worker
PALLAS_SHARD_ID=0
PORT=8090
```

worker-1：`PALLAS_SHARD_ID=1`、`PORT=8091`，须与 `data/pallas_shard/registry.json` 中 `shards[].port` 一致。

### 配置是否共用

| 项 | 说明 |
|----|------|
| **`config/pallas.toml`** | 各进程读取同一份（数据库、`HOST` 等 bootstrap；WebUI 项在共享 `data/pallas_config/webui.json`） |
| **按进程覆盖** | `run_sharded_bot.sh` 用 `env KEY=val` 设置 `PALLAS_BOT_ROLE`、`PALLAS_SHARD_ID`、`PORT` 等，**优先于磁盘配置同名项** |
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
- 新建协议端账号 / relogin「创建牛牛」时自动 `assign_bot_to_shard(qq)`，并写入该牛专属的 `ws_url`。
- 跨进程 **claim**（`data/*/message_claims`）与 worker **`_ingress_gate`** 依赖共享 `data/`。

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

| 能力 | 目录 / 模块 | 说明 |
|------|-------------|------|
| 牛牛报数顺序 | `coord/bot_count/` | 各片登记 → 收集窗口 → 最小 QQ finalize 顺序 |
| 决斗 QTE 代答 | `coord/duel_qte/` | 主持片写会话，应答牛所在片 watcher 回写 |
| 同群决斗互斥 | `coord/duel_group/` | 跨片占用 |
| 指定牛代发 API | `coord/bot_action/` | 跨片请求 + watcher |
| 群级短占位 | `coord/group_gate/` | 含 `pallas_image` owned gate |
| 在线态 / WebUI | `worker_presence.json` | hub 读各 worker 连接 |
| 控制台指标 | `stats/worker-{N}.json` | hub 合并展示 |
| registry / fleet | `registry.json` + mtime | `shard_data_sync` 失效缓存 |

worker 由 `src/common/shard/coord/worker_poll.py` 轮询 `duel_qte`、`bot_action` 待办。

## WebUI 与日志（hub）

- `GET /pallas/api/bots`：读 **worker_presence.json**（hub 无反向 WS）。
- `GET /pallas/api/logs`：合并 `data/pallas_shard/logs/hub.log` 与各 `worker-*.log` 尾行（`sharded_logs: true`）。
- `plugin-run-stats` / `message-stats`：合并各 worker 的 `stats/worker-*.json`；ERROR 日志合并 worker/hub 落盘文件。
- 实时 SSE 以 **hub 本进程** 为主；查全集群历史建议日志页轮询。

## AI 与 MAA 回调

- **Pallas-Bot-AI**：`http://<hub>:<PORT>/callback/{request_id}`；任务登记在 worker，hub `callback` 插件转发到对应 worker。
- **牛牛画画**、**MAA 远控**：不走 AI callback；MAA 客户端轮询 hub，`maa_hub` 按 QQ 转发至登记 worker；`maa_public_base_url` 填 **hub 对外基址**。

## PostgreSQL 连接池

同一 worker 上多只牛会各收到群消息；未抢到 ingress 的会话可能伴随 `asyncio.CancelledError`。若出现 **non-checked-in connection**，多为预处理器被取消时连接未归还（代码侧已 `shield` / `invalidate` 兜底）。

生产请估算：**worker 数 × `PG_POOL_SIZE` < PostgreSQL `max_connections`**，并预留其他应用连接。

## 多 Bot 同群行为摘要

- **`_ingress_gate`**（worker）：全集群 fleet、@ 定向、ingress claim、greeting/报数 fanout。
- **fanout 白名单**：WebUI「分片全员同响白名单」或 `PALLAS_INGRESS_FANOUT_GREETING`；**`牛牛报数` / `牛牛出列` 恒 fanout**。
- **`duel` / 八角笼**：跨片 `coord/duel_group`、`bot_action`、`duel_qte`。
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
