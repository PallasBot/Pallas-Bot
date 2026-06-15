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

## Phase 3 — 插件代码瘦身（当前可开工）

**原则**：unified 路径为默认实现；分片分支用薄适配层，避免每插件复制 ingress/coord 逻辑。

| 优先级 | 范围 | 方向 |
| --- | --- | --- |
| P0 | `help`、`repeater`、`bot_status` | `help`/`repeater`/`bot_status` 已迁 `shard.context`；报数逻辑抽出 `shard_count.py` |
| P1 | `duel`、`dream`、`who_is_spy` | 统一走 `group_activity` / `hosted_activity`；删 per-game 薄封装 |
| P2 | 其余含 `is_sharding_active` 的插件（约 30 处） | 迁到 `shard.context` + 少量 hook |
| P3 | `ingress_gate` 插件本体 | 仅保留 worker/unified 必需逻辑；hub 路径再瘦身 |

每插件 PR：**行为不变**为前提，先补/跑 shard 相关测试再删分支。

## Phase 4 — 文档与站点

| 任务 | 说明 |
| --- | --- |
| `control-plane-corpus-federation.md` | 用户可见段落下沉 `corpus/README`；路线图降导航权重 |
| `noobook/`（Docs 站） | 评审归档或迁独立分支（~2900 行） |
| `docs` 分支 | 评估是否仍需要「冲突以 docs 为准」双分支 |
| 插件文档 | 对外名 `draw` 与配置键 `pallas_image_*` 一次性说明，避免再漂移 |

## 分支与提交约定

- 瘦身工作分支：`chore/next-gen-slimdown`（自 `main`）
- 一类问题一 PR：`refactor(shard): …` / `docs(architecture): …` / `refactor(ingress): …`
- Phase 2 起每个插件瘦身尽量独立 PR，便于回滚

## 参考

- [多进程分片](bot_process_sharding.md)（可选部署）
- [内核分层](common-layers.md)
- [开发指南](../develop/README.md)
