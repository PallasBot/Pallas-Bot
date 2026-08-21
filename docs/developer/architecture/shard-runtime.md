# 多实例运行时（分片兼容）

日常部署和运维只使用 `pallas run`、`pallas status`、`pallas restart`、`pallas logs`；它们呈现为统一运行时与运行实例，自动沿用当前编排。单实例是默认路径：一个进程接入本机账号，以会话公平调度、命令优先和背压控制处理高峰，不需要 Redis，也不因账号数量自动改用分片。

需要多机部署、账号级隔离、高可用或显式横向扩缩容时，才使用 `pallas run shard` 与本页的分片兼容细节。此时分片是集群拓扑；Redis 是跨进程协调的事实源。

本页说明多实例后端的进程角色、编码约束与跨进程能力。部署与启停见 [分片部署](/maintainer/deploy/sharded)。涉及同群多牛、跨 worker 去重、群独占活动或媒体 callback 回到发起 worker 时，再按本页设计。

## 何时用分片

当存在多机部署、账号隔离或高可用需求时，在共享同一 `data/` 与 Redis 的前提下拆为 **1 hub + N worker**。不要仅因单机账号数量多就切分；应先通过统一运行时的 ingress、调度器、发送队列与数据库指标确认瓶颈。

| 进程 | 职责 |
| --- | --- |
| Hub | WebUI、协议端管理、注册表、AI/MAA 回调入口；不接 Bot 反向 WebSocket |
| Worker | 群消息与玩法主路径；每进程约 `PALLAS_SHARD_BOTS_PER` 只账号 |

跨进程 claim 依赖 Redis（`REDIS_URL` / `PALLAS_COORD_REDIS_URL`）；与 AI 仓可共用。详见 [分片部署](/maintainer/deploy/sharded)。

玩法专属协调（duel、dream、maa、spy 等）在 `pallas/extensions/coord/{duel,dream,maa,spy}/`；`pallas/core/platform/shard/coord/` 下旧路径为兼容 shim。通用 claim/presence 与 `worker_port.py` 仍在 core。

## 拓扑

![Pallas-Bot 分片运行时拓扑：Hub、Worker、Redis、协议端与可选 AI Runtime 的职责和连接关系](/assets/shard-runtime-topology.svg)

图中 AI 为媒体 / RWKV Runtime；普通聊天仍在 worker 内走 Bot Provider，不经该边。

## 角色

| 角色 | 职责 | 代码锚点 |
| --- | --- | --- |
| Hub | 协调、控制台聚合、部分入口；非主要消息处理 | `is_sharded_hub` / `is_hub_role` |
| Worker | 插件与群消息主路径 | `is_sharded_worker` |
| Redis | 分片协调事实源（非可丢弃缓存） | 通用 claim/presence（core）；玩法协调见 `pallas/extensions/coord/{duel,dream,maa,spy}/` |
| Protocol | 账号接入，连到 worker | 协议扩展 |

角色探测：`from pallas.api.platform import is_sharded_hub, is_sharded_worker, is_sharding_active`。

## 编码约束

| MUST NOT | MUST |
| --- | --- |
| 假设 hub 本地已加载全部运行中插件 | 需要全局视图时走 worker 聚合 / registry |
| 把进程内状态当集群全局状态 | 跨 worker 用 Redis / 共享注册表 |
| 在 async 热路径做阻塞轮询 | 用既有 listener / pubsub 模式 |

## 高频能力

| 能力 | 约束 | API（`pallas.api.platform`） |
| --- | --- | --- |
| 消息去重 / claim | 同条消息不可多 worker 重复响应 | `try_claim_group_message_once`、`claim_group_message_event`、`claim_group_handler`（core）；玩法协调见 `pallas/extensions/coord/` |
| 群独占活动 | 同群同时一场 | `begin_group_exclusive_activity`、`try_begin_group_owned_gate` |
| Fanout / host gate | ingress 策略与主持牛 | `text_matches_plugin_fanout`、`dream_session_ingress_passes` |
| 跨分片发送 | 指定 bot 代发 | `send_group_message_as_bot`、`invoke_bot_action` |
| Hub-only 启动逻辑 | 勿在 worker 重复挂载 | `startup.py` 内 `is_sharded_worker()` 守卫 |

## 触发分片设计的改动

涉及任一项即按分片设计：

- 同群多牛
- 跨 worker 去重
- 指定某 bot 执行动作
- 群级独占活动
- 媒体 / RWKV callback 回到发起 worker
- WebUI 展示 worker 实时态

## 禁止

| 禁止 | 原因 |
| --- | --- |
| 仅在单进程验证上述能力 | 分片下会重复响应 / 丢状态 |
| hub 读本地插件态做全局结论 | 遗漏 worker 专属插件 |
| 把 Redis 当可丢弃缓存 | 协调层事实源 |

## 后续阅读

- [架构总览](overview.md)
- [Core 与扩展](core-vs-extensions.md)
- [多牛协同面](multi-bot-collaboration.md)
- [Platform API](/developer/reference/platform-api)
- [分片部署](/maintainer/deploy/sharded)
