# 运维脚本索引

> **4.0 运维**：推荐统一 CLI **`./scripts/pallas`**（见 [pallas-cli.md](../docs/architecture/pallas-cli.md)）。`run_*_bot.sh` 为兼容入口，由 `pallas run|stop|restart` 内部调用。

| 目录 | 用途 |
| --- | --- |
| `scripts/pallas` | **统一 CLI**（推荐：`doctor`、`sync`、`ext`、`update`、`run`、`maintenance`） |
| `scripts/run_unified_bot.sh` | 单进程启停（**兼容**；内部仍由 `pallas run unified` 调用） |
| `scripts/run_sharded_bot.sh` | 分片启停（**兼容**） |
| `tools/scripts/` | 备份、watchdog、文档同步 |

## 单进程 unified

| 脚本 | 说明 |
| --- | --- |
| `run_unified_bot.sh` | `start` / `stop` / `restart` / `status` |
| `sync_unified_protocol_ports.py` | 对齐协议端 `ws_url` 到 unified 监听端口 |
| `migrate_shard_to_unified.py` | 分片迁回单进程 |
| `migrate_unified_to_shard.py` | 单进程迁分片 |

## 分片

| 脚本 | 说明 |
| --- | --- |
| `run_sharded_bot.sh` | hub + worker 启停；子命令见 `-h` |
| `lib/shard_lib.sh` / `lib/shard_cmds.sh` | 分片启停实现，供 `run_sharded_bot.sh` source |
| `sync_shard_protocol_ports.py` | 协议端 `ws_url` 对齐各 worker 端口 |
| `detect_shard_redis.py` | 探测 Redis，供启停脚本调用 |
| `apply_shard_worker_ports.py` | 写注册表 worker 端口 |
| `shard_startup_ports.py` | 启动前端口评估与写回 |
| `wait_shard_worker_ports.py` | 等待 worker 端口可 bind |
| `calc_worker_count.py` | 估算 worker 数量 |
| `shard_registry_repair.py` | 注册表 compact / restore-production |
| `shard_registry_presence_diff.py` | 注册表与 presence 差异 |
| `shard_coord_snapshot.py` | coord Redis 快照 |
| `shard_observability_snapshot.py` | 可观测 JSON |
| `shard_observability_status.py` | 可观测终端摘要 |

## 分片测试

| 脚本 | 说明 |
| --- | --- |
| `shard_test_enter.sh` / `shard_test_leave.sh` | 进入 / 离开测试 worktree |
| `shard_test_worker.py` | 测试分片 worker 管理 |
| `shard_test_migrate_ports.py` | 测试端口迁移 |

## 插件资源

| 脚本 | 说明 |
| --- | --- |
| `sync_arknights_data.py` | 方舟数据同步（决斗六星表、头像、档案、敌人图鉴） |
| `fetch_arknights_duel_data.py` | 兼容入口 → `sync_arknights_data.py` |
| `cache_ark_lore_for_duel.py` | 兼容入口 → `sync_arknights_data.py --maintainer-lore` |
| `generate_pallas_help_style.py` | 帮助图样式生成 |

## tools/scripts

| 脚本 | 说明 |
| --- | --- |
| `sync_docs_to_web.py` | 主仓 `docs/` → Pallas-Bot-Docs |
| `bot_watchdog.py` | `/pallas/api/health` 探活重启 |
| `backup_database.py` / `backup_pg.py` | 数据库备份 |
| `backup.sh` / `backup_pg.sh` | shell 备份入口 |
| `clear_old_image.py` | 清理旧画图缓存 |

分片详情见 [多进程分片](../docs/architecture/bot_process_sharding.md)。
