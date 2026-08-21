# 多牛协同面（同群多牛 / 联邦 / 分片）

本页描述**同群多牛**场景下 Pallas 如何组织「谁是本舰」（fleet）、「谁在线」（presence）、「一条消息只处理一次」（claim/dedup）与「跨部署协作」（federate）。分片的进程角色与部署见 [分片运行时](shard-runtime.md)；跨部署的用户侧行为见 [多机协同](/common/corpus)。

核心不变量与分片相同：**Redis 是跨进程协调的事实源（非可丢弃缓存）**；所有群消息去重、群独占、群归属都依赖它。单进程统一运行时（unified）不连 Redis，跨牛去重退化为进程内/本地文件 claim。

## 抽象层级

| 层 | 模块 | 视角 | 代表 |
| --- | --- | --- | --- |
| 本进程已连接牛 | `multi_bot/connected_roster.py` | 本进程连了几只牛 | `connected_bot_ids()` |
| 全集群应认作自己人的号 | `multi_bot/fleet.py` | 本舰全部（分片 registry ∪ 会话） | `get_fleet_bot_ids()` |
| 曾建立过连接的号 | `multi_bot/session_seen.py` | 跨进程共享文件 | `get_session_seen_bot_ids()` |
| worker 在线态 | `shard/presence.py`+`presence_health.py` | hub/WebUI + 联邦 online 口径 | `get_cluster_online_bot_ids()` |
| 同部署内消息去重 | `multi_bot/dedup.py` | 同条群消息本舰只处理一次 | `try_claim_group_message_once` |
| 同群独占/占位 | `multi_bot/dedup.py` owned gate | 同群短时单牛发言 | `try_begin_group_owned_gate` |
| 跨部署联邦名册 | `federate/peer_bots.py` | 协同池其它部署的牛 | `get_federate_peer_bot_ids()` |
| 跨部署消息抢占 | `federate/ingress.py` | 同池各端抢同一条 | `claim_federate_group_message_ingress` |

## Fleet（本舰视角）

`fleet` = 本部署（分片是全部 worker，单进程是本进程）应认作「自己人」的 QQ 集合：

- `get_fleet_bot_ids()`：分片下为 `enabled accounts ∪ registry assignments/workers ∪ 本进程 session_connected`；单进程退化为 `connected_bot_ids()`。
- 群在线缓存 `group_online_cache.py` 按群缓存在线 fleet/本进程已连牛（双 namespace、TTL 45s、上限 512），避免高频 `get_group_member_info`。
- 友军互认：`is_fleet_bot_qq`（分片 fleet ∨ 联邦 peer ∨ 本地 connected）、`is_other_bot` 拦截其它牛消息（`bot_filter.py`，priority 1/4 block matcher）。
- @ 目标解析：`message_at_fleet_bot`（fleet ∪ federate peers）、`group_at_qq_ids`。

## 群消息去重（claim / dedup）

协议会把一条群消息向本舰每个已连接账号各上报一次，因此**用消息内容签名去重**，而非 on 协议 message_id：

1. **签名**：`cross_bot_message_signature(group_id, user_id, body[, message_time])` 默认三元 `(群, 用户, 归一化正文)`；`include_message_time=True` 四元（决斗/八角笼按场次区分）。`cross_bot_group_message_key` = `sha256[:15]` 整数。
2. **进程内**：`try_claim_group_message_once(plugin, group_id, sig)` 本进程整条约 4000 key 内存去重，`claim_key=0` 占位。
3. **跨 bot**：`try_claim_cross_bot_message` 按连接的 bot_id 抢占持久化 claim。
4. **跨 shard**：`try_claim_cross_shard_message` 全舰队一条消息只由一个 shard 通过，shard 内各牛不再互斥（`ingress_shard_claim_owner_obsolete` 允许过期 registry shard 覆盖）。

持久化 claim：分片/多进程走 Redis `pallas:msg_claim:{plugin}:{group}:{message_id}`（TTL 86400s）；单进程落到 `data/<plugin>/message_claims/{group}_{message_id}.claim`（O_EXCL 原子创建，按 mtime 保留最新 500、超 1 天删）。入口 `try_claim_message_sync(plugin, group_id, message_id)`；便捷 API：`claim_group_message_event`（是否应处理本条）、`claim_group_handler`（私聊恒 True）、`should_skip_duplicate_group_event`。

**群独占/占位**（同群短时单牛发言）：`try_begin_group_owned_gate` / `try_acquire_group_broadcast_slot` / bind-release；分片委托 `shard/coord/group_gate.py`。**群独占活动**（同群同时一场）：`begin_group_exclusive_activity(namespace, group_id)`，分片委托 `shard/coord/group_activity.py`。

## Presence（在线态）

worker 的 WS 连接状态：

- 存 Redis HASH `pallas:presence:bots`（field=QQ，字段 qq/shard_id/connection_key/adapter/connected_at_unix/last_seen_at/nickname）；单进程退化为共享文件 `worker_presence.json`。无单键 TTL，靠按 `last_seen` 超 120s 清理。
- 写：连接/断开钩子（`note_worker_bot_connected/disconnected`）、周期性 `touch_worker_bot_presence_sync` / `reconcile_local_worker_presence_sync`、协议离线通知 `mark_protocol_bot_offline`。
- 读：hub WebUI `/bots`、`get_cluster_online_bot_ids`（联邦 online 口径）、`bot_has_cluster_connection`、`count_connected_bots_for_reporting`。
- 健康：连续 3 次 `get_status` 失败入 quarantine 踢出僵尸 WS（60s 最小间隔、并发 8）；被隔离视为离线。

## Federate（跨部署联邦）

同一个 federate 池内多个 deployment（各可持多牛）在同一群协作，**全基于 Redis TTL 心跳发布 + SCAN 前缀发现**，无清单式名单。

- **配置**：`PALLAS_FEDERATE_ID`、`PALLAS_FEDERATE_INGRESS_ENABLED`（auto：有 ID 即开）、`PALLAS_FEDERATE_INGRESS_BYPASS_UNIFIED`（单进程时跳过）、`PALLAS_FEDERATE_REDIS_PREFIX`、`PALLAS_FEDERATE_OWNER_ROTATE_SEC`（默认 7200）、`PALLAS_FEDERATE_PREFER_LOCAL_OWNER`（默认关）。`PALLAS_CONTROL_PLANE_ENABLED=false` 禁用联邦。coord Redis URL：显式 `PALLAS_FEDERATE_COORD_REDIS_URL` → bootstrap 落盘 → 无则禁用；`federate_redis_prefix()`：bootstrap coord prefix → 显式 prefix → `pallas:fed:{safe_fid}`。
- **peer 名册**：心跳发布 `publish_local_federate_peer_bot_ids_sync`（SET ex=180s，最小 60），payload 含 `bot_ids / online_bot_ids / public_bot_ids / public_online_bot_names / present_group_ids / command_capabilities / command_permission_levels / capability_protocol(v2) / ingress_protocol(v2) / ingress_capabilities`；对端 SCAN `pallas:fed:*:peer_bots:*` 解析。同步循环默认每 60s；连接钩子与启动即时同步。
- **在场群**：`touch_federate_present_group` 每群消息 touch 写 ZSET（score=时间戳，窗口默认 300s、上限 2000）。
- **公开面**：`get_federate_peer_bot_ids`、`get_federate_bot_rosters`（WebUI 多机协同页）、`federate_peer_bot_ids_contains(qq)`（友军互认）、`federate_peer_declared_command_plaintext(plain)`（对端宣告能力覆盖时当命令流量）。

### 群归属（命令路由）

`federate_group_owner_deployment` 用各方一致的确定性算法选「本群命令的主要处理部署」，环内依次过滤：

1. **能力环** `_capable_owner_ring`：只在显式宣告能覆盖该命令明文的部署里取模；无人显式→本机可覆盖则本机独担→再无人则全员环（未宣告视为不抢，避免旧端抢走新命令）。
2. **权限环** `_permission_owner_ring`：按命令权限等级只留最宽松部署（避免严格端被轮到时权限失败）。
3. **在场环** `_present_owner_ring`：只在实际在场群部署间取模，`None`（未宣告）视为可能在场。
4. **时间桶**：`blake2b(group_id:epoch)` 取模；`rotate_sec<=0` 时纯群号取模；默认 7200s 轮换。

`prefer_local_owner` 开则本机在环内时直接当 owner。**仅命令车道走归属**；chat 车道（@ 牛牛、复读）与跨部署 claim 只按条防双回。

### 联邦 ingress 抢占

`claim_federate_group_message_ingress` 独立于 multi_bot claim：用 `cross_bot_message_signature` 签名，先查进程内 winner 缓存（TTL 8s、上限 20000）+ inflight future 共享结果，再 Redis `SET NX`（`{fed_prefix}:ingress:{plugin}:{group}:{claim_key}`，TTL 86400）。有 candidate 机制（最小候选号赢，TTL 2s）。`try_claim_cross_federate_message`（`federate/dedup.py`）用于需要彻底无竞争的（复读 fanout 等）。无 peer 对端时直接放行，避免协调 Redis 丢单条。审计 `federate_ingress_audit_summary_sync` 记 `{capability}:{outcome}`（TTL 300s）。

## 命令 vs 归属范围

| 场景 | 跨部署 | 说明 |
| --- | --- | --- |
| 普通命令（明文识别） | 群归属 + claim | 粘性归属只作用于命令，防两端同时进匹配器 |
| 群内闲聊、@ 牛牛聊天 | 仅 claim | 按条决胜负，避免热群把整台机器钉死 |
| 复读 fanout / 全员同响 | 故意跳过 claim | 多头/多端齐回 |
| 事件 / notice | 同进程 once | `try_claim_group_message_once` 即可 |

## 边界与禁止

| 禁止 | 原因 |
| --- | --- |
| 进程内集合当集群全局状态 | 分片下不一致 |
| 直接用 message_id 去重 | 各连接 message_id 不同 |
| 高并发重复打成员列表 API | 走 `group_online_cache` 45s 缓存 |
| 把联邦名单当配置 | 靠心跳发现、TTL 收敛 |
| 在 async 热路径阻塞轮询 | 用既有 claim/listener 模式 |

## 后续阅读

- [分片运行时](shard-runtime.md)
- [多机协同（用户侧）](/common/corpus)
- [Platform API](/developer/reference/platform-api)
- [分片部署](/maintainer/deploy/sharded)