# 下一世代瘦身路线图

面向 **单进程 unified 为主**、分片为可选生产部署的演进。主仓 `docs/` 为权威来源；本文供维护者与 Agent 对齐阶段边界。

## 已完成（Phase 0–2）

| 项 | 说明 |
| --- | --- |
| ingress fanout 元数据化 | `policy_registry` + 各插件 `ingress_fanout`；移除分散 `*_plaintext` 模块 |
| unified 启停 | `run_unified_bot.sh`、分片↔unified 迁移与协议端口同步 |
| 文档减负 | `docs/develop/` 迁入主仓；`AGENTS`/`CONTRIBUTING` 去重；Docs 同步映射补齐 |
| 分片运维拆分 | `run_sharded_bot.sh` → `scripts/lib/shard_lib.sh` + `shard_cmds.sh` |
| coord legacy 清理 | 移除 Redis 化后的空 `prune_stale_*` / `poll_*` 桩 |
| presence 分片单路径 | `is_sharding_active()` 时仅写 Redis，单进程仍可回退文件 |
| unified ingress 语义 | 仅**显式** `ingress_fanout` 跳过 once-claim；未声明口令走 shard 级 claim |
| shard context API | `src/platform/shard/context.py`：`sharding_active()`、`role()`、代表牛 |
| coord listener 注册表 | `worker_poll.coord_listener_starters()` 集中登记 |
| ai_task 单层 | `ai_task_registry_redis` 并入 `ai_task_registry` |
| coord 快照脚本 | `prune_shard_coord.py` → `shard_coord_snapshot.py` |

## Phase 3 — 插件代码瘦身（已完成）

**原则**：unified 路径为默认实现；分片分支用薄适配层，避免每插件复制 ingress/coord 逻辑。

| 优先级 | 范围 | 状态 |
| --- | --- | --- |
| P0 | `help`、`repeater`、`bot_status` | 已迁 `shard.context`；`bot_status` 抽出 `shard_count.py` / `list_mode.py`；`repeater` 全模块完成 |
| P1 | `duel`、`dream`、`who_is_spy` | `duel` 抽出 `shard_cage.py`；`dream` 抽出 `shard_fleet.py`；`who_is_spy` 已走 `hosted_activity_ingress` |
| P2 | 其余含 `is_sharding_active` 的插件 | 已完成；`pallas_webui` 经 `_shard_hub_console` / `_shard_worker_console` 收敛 |
| P3 | `ingress_gate` 插件本体 | 已完成；claim 迁入 `platform/ingress/claim_gate.py`，hub 经 `shard.context.is_hub()` 禁用 |

## Phase 4 — 文档与站点（进行中）

| 任务 | 状态 |
| --- | --- |
| `control-plane-corpus-federation.md` 用户段落下沉 | 已完成；用户向见 [语料联邦](../common/corpus/README.md) |
| 路线图 / 控制面导航降权 | 已完成；主仓与 Docs 站侧栏调整 |
| 插件 `draw` 与 `pallas_image_*` 命名说明 | 已完成；见 [draw 插件文档](../plugins/draw/README.md) |
| `noobook/` Docs 站归档降权 | 已完成；移出顶栏，侧栏保留并标注 legacy |
| `docs` 双分支策略 | 维持现状：`main` 为 `docs/` 权威来源；`docs` 分支仅 CI 合并缓冲，冲突时 `-X ours` 以 `docs` 为准 |

## 分支与提交约定

- 瘦身工作分支：`chore/next-gen-slimdown`（自 `main`）
- 一类问题一 PR：`refactor(shard): …` / `docs(architecture): …` / `refactor(ingress): …`
- Phase 2 起每个插件瘦身尽量独立 PR，便于回滚

## 参考

- [多进程分片](bot_process_sharding.md)（可选部署）
- [内核分层](common-layers.md)
- [开发指南](../develop/README.md)
