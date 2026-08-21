# Corpus 复合语料仓

语料仓是 Repeater 接话的唯一数据来源，也是社区共享接话库 / 联邦语料的总线。它以「**本机 local 为唯一写目标**，fed / community 只读（写经异步 mirror/backfill 上传）」为心智模型，用**透明包装**接进 `ContextRepository` 协议，对 Repeater 热路径无侵入。

```text
Repeater 接话（bundle_lookup → Responder）
  └─ context_repo：pallas.core.foundation.db.context_repo_access（进程共享单例）
       └─ factory.maybe_wrap_composite(local)  —— 透明包成 CompositeContextRepository
            ├─ local：PG 主库（写目标 + 接话快照）
            ├─ fed：未实现占位（factory.build_fed_repository → None）
            └─ community：HTTP（GET /context 读、POST /contribute 写）
  旁路：prefetch（拉远程预热本地） / write_fanout（本机写 mirror 上传） / backfill（历史同步）
```

## 能力全景

| 能力 | 说明 | 默认 |
| --- | --- | --- |
| 本机接话 | local 库查语料（限量快照 SQL） | 开启 |
| 社区共享库 | 接话查社区池（remote find） | `auto`→off（`PALLAS_CORPUS_REMOTE_FIND_ENABLED`） |
| 向社区贡献 | 本机新学短句异步 POST /contribute | `auto`→开（可被中心 enroll 策略关闭） |
| 联邦 fed 源 | 第二写源/读源 | **未实现**（Phase 占位，`factory.py:34-39`） |
| 历史回填 | 本机历史语料渐进同步社区 | `PALLAS_CORPUS_BACKFILL_ENABLED=false` |

- 查找顺序：`merge_order`（默认 `local,fed,community`，`config.py:40,52-60`），仅保留三源之一。
- 合并策略 `merge_strategy`：`local_first`（本地命中即短路）/ `merge_counts`（跨源合并计数）。
- composite 开关：`corpus_composite_enabled = fed_on ∨ community_on`；community_on = community_wanted ∧ (configured ∨ auto_enroll_enabled)（`config.py:198-202`）。

## 配置层

`CorpusConfig`（`config.py:37-49`）经 `get_corpus_config`（`@lru_cache`，`config.py:174-191`）读取，全部走 `repo_env_raw_value`（`pallas.toml → .env → webui.json` 合并）。任意修改后必须 `clear_corpus_config_cache()`。

| 键（前缀 `PALLAS_CORPUS_`） | 默认 | 语义 |
| --- | --- | --- |
| `MERGE_ORDER` | `local,fed,community` | 查找顺序 |
| `MERGE_STRATEGY` | `local_first` | `local_first` / `merge_counts` |
| `FED_ENABLED` | `auto` | tri-state，与 `fed_configured()`（PG 第二连接 env）合成 |
| `COMMUNITY_ENABLED` | `false` | tri-state，社区共享库总开关 |
| `AUTO_ENROLL` | `false` | 自动向中心登记口令；`auto` 跟随「使用社区共享接话库」（`config.py:86-98`） |
| `COMMUNITY_CONTRIBUTE` | `auto` | 是否向社区贡献；仅显式 `false` 关闭（`config.py:153-160`） |
| `ON_REMOTE_FAILURE` | `local_only` | 远端故障兜底；WebUI 固定 `local_only` |
| `COMMUNITY_API_BASE` / `TOKEN` | `""` | 手工凭证 |
| `REMOTE_FIND_ENABLED` | `auto`(→off) | `off` / `sync`（热路径同步查远程）/ `prefetch`（miss 后台拉，下次再回） |

性能段（`reply_perf_config.py:97-106`）：`REPLY_MESSAGES_CAP(16)` / `REPLY_ANSWERS_CAP(128)` / `FIND_CACHE_SEC(45)` / `FIND_CACHE_MAX(50000)` / `REPLY_SNAPSHOT_SEC(5)` / `REPLY_SNAPSHOT_MAX(20000)` / `REPLY_QUERY_TIMEOUT_SEC(2)`。

凭证解析优先级：手工 env → community_stats 自动 endpoint 推导（`community_stats/endpoints.py:79-82`）→ 落盘 `corpus_community.api_base`（`config.py:118-150`）。

## 存储层

### ContextRepository 协议（`core/foundation/db/repository.py:41-94`）

`find_by_keywords` / `context_exists_by_keywords` / `save` / `insert` / `delete_expired` / `find_for_cleanup` / `upsert_answer` / `replace_answers` / `append_ban` / `find_ban_reply_target` / `list_answers_for_group_since`。composite 与其各源都挂此协议，上层无感知。

### 复合仓库（`composite_repo.py:24-335`）

- 构造 `(local, fed=None, community=None, cfg=None)`；`maybe_wrap_composite(local)`（`factory.py:23-49`）在 `make_context_repository()` 时对共享 repo 做包装（`db/__init__.py:527-537`）。
- 读路径：`find_by_keywords` → `cached_find_by_keywords`（find_cache）；`find_by_keywords_for_reply`（接话热路径，`composite_repo.py:54-72`）→ `_find_by_keywords_merged`（sync 模式全源合并，`composite_repo.py:95-150`）：按 `merge_order` 遍历，非 local 源先过 `should_skip_remote_corpus(hot_path=True)` 池压门禁，`merge_contexts` 逐源合并，`local_first` 下 local 有答案即短路（outcome=`local_short_circuit`）。
- 写路径：全部落 local + 异步 mirror（见「学习写回与 fanout」），并逐 key `invalidate_find_cache`。

### 各来源读写

| 源 | 读 | 写 | 实现 |
| --- | --- | --- | --- |
| local | `find_by_keywords` / `_find_by_keywords_for_reply_snapshot`（`repository_pg.py:1293-1403`，限量快照：每条消息 ≤ msg_cap、每词 top Answer ≤ ans_cap，按关键词长度收紧） | `learn_answer`（`repository_pg.py:1610-1679`，`ON CONFLICT` + `xmax=0` 判 was_insert）/ `upsert_answer`（1553-1608） | PgContextRepository / Mongo 版 |
| fed | 未实现（`build_fed_repository` 恒 None） | 同上 | — |
| community | `RemoteCorpusRepository.find_by_keywords` → `GET {base}/context?keywords=`（`community_source.py:105-155`，多 base 容错、401 触发 re-enroll、404/无 dict → None） | `POST {base}/contribute`（`community_source.py:160-237`，200/202 成功、401/403 re-enroll） | 纯 HTTP（httpx.AsyncClient，Bearer token） |

### 数据与落盘

- Context/Answer/Ban 为 pydantic 模型（`core/foundation/db/modules.py`），PG 表 `context` / `context_answer` / `context_answer_message` / `context_ban`。**实体数据全在业务库，不落 data/ 文件**。
- 本地文件仅三类状态：
  - `data/pallas_config/corpus_backfill.json`：backfill 游标 `{cursor_keywords, wrapped_unix, updated_unix}`（`backfill_store.py:9-24`）。
  - community_stats store 的 `corpus_community` 块：`{api_base, corpus_token, enrolled_at, expires_at?, contribute?}`（`store.py:11-35`）。
  - community usage 为进程内缓存不落盘。

### find_cache（`find_cache.py`）

`_find_cache`（合并查）与 `_reply_find_cache`（接话查）双 TTL 缓存 + inflight 单飞（`asyncio.shield`）；`_REPLY_DB_FAIL_TTL_SEC=2.0` 短负缓存（`is_pg_pool_timeout_error` 后 2s 跳过接话查询）。`invalidate_find_cache(keywords=None)` 传 None 全清。PG 侧另有 `cached_reply_query_snapshot` LRU（`repository_pg.py:1171-1249`），WebUI 保存性能段时全清。

文本规范化：`text_util.plain_message_text`（去 `\x00` → 剥 `[CQ:xxx]` → 折叠空白），用于热词标名、backfill 挑句。

## 回填 / 预热 / 热词链路

| 链路 | 触发 | 行为 | 门禁 |
| --- | --- | --- | --- |
| local_hot 热词（`local_hot.py`） | WebUI `GET /api/local-corpus-hot`（`stats_dashboard_api.py:181-198`，60s 缓存）/ community_stats heartbeat 附带 `corpus_hot_snapshot`（每 900s） | PG 一次 CTE SQL（top_ctx 按 `SUM(answer.count)` + 每词 top N），Mongo 两段聚合管道 | `aggregate_local_hot_keywords(limit≤80, answers≤8)` |
| backfill 历史同步（`backfill.py`） | `should_run_corpus_backfill`（`backfill.py:66-76`）= 非分片 worker ∧ `BACKFILL_ENABLED` ∧ contribute_enabled ∧ enroll 有效 ∧ `build_community_repository()` 非 None | 按 `cursor_keywords` 升序翻页 → 每 context 取首条有效 message 逐 Answer `upsert_answer(group_id=0, append_on_existing=True)` 上传 | `consume_backfill_rate_slot` 每分钟 ≤ `MAX_PER_MINUTE`；每 item 前池压 >0.78 或 mirror 队列满则跳过 |
| backfill 调度（`backfill_scheduler.py`） | apscheduler interval（默认 1800s，首跑延迟 120s，coalesce/max_instances=1） | 经 repeater startup `bind_corpus_backfill_lifecycle` 注册；WebUI 保存配置时 `reload_corpus_backfill_job` 重挂 | — |
| prefetch 预热（`prefetch.py`） | 热路径 local miss 且 mode=prefetch → `schedule_corpus_prefetch(keywords)`（`composite_repo.py:68-71`，`put_nowait` **不阻塞**） | `import_remote_context_to_local`：local 已有答案则跳过；不存在整条 insert，否则逐 Answer upsert（group_id 原样保留，走 local insert 不经 mirror，**防回环**） | 三重：①全局 池压>0.15/learn 队列压力/队列水位（`_QUEUE_MAX=4096`，>64 算压力）②短词延迟：≤6 词 45s 内 miss ≥2 次才拉 ③key 级 90s 去重 |

## 学习写回与 fanout

写回链路（避免在消息进程写语料）：

```text
群消息 → handlers/message.py enqueue_repeater_learn（learn_queue.py，只入队）
  → work aux: repeater.learn → Learner.process_work_payload → _context_insert（learner.py:125-195）
      排除复读句（pre_msg == raw_message）与含 [CQ:reply, 的引用消息
      首选 context_repo.learn_answer（composite 代理）：
        ① reject_corpus_learn_message（污染防护）→ false 直接放弃
        ② local.learn_answer（PG 原子 upsert，返回 was_insert）
        ③ invalidate_find_cache → schedule_mirror_insert / schedule_mirror_upsert_answer
  兜底旧路径：context_exists_for_learn（context_exists_cache.py:88-117，45s TTL）→ upsert / insert
```

- `write_fanout.py`：单 worker 队列（`_WRITE_QUEUE_MAX=2048`，`corpus_write_concurrency()==1`）的异步 mirror。
  - 门禁：`cfg.fed_contribute ∨ community_contribute_enabled(cfg)` 才入队；`should_skip_noncritical_db()`（db_health）或 PG 池 >0.78 记 `note_mirror_skipped_pressure` 直接放弃；队满丢弃计数。
  - **去标识化**：community 上传 `group_id=0`，insert 经 `community_mirror_context` 把全部 Answer 的 group_id 抹为 0 再 POST（`write_fanout.py:18-37`）——不传群号/QQ。
  - community 侧包 `RemoteCorpusBudget(hot_path=False, wait=True)`（可排队等槽，`community_source.py:197-206`）。
- 污染防护（横切附注）：`pallas/product/llm/corpus_contamination.py`，composite 的 `upsert_answer`/`learn_answer`/`insert` 全部先 `reject_corpus_learn_message`（命中污染词条短语直接返回 False，`corpus_contamination.py:249-256`，受 `LLM_CORPUS_LEARN_GUARD_ENABLED` 控制）；另有每日清理任务。

## 社区 / 联邦

### 社区（community）

- config 读取：`community_configured()` = 手工 env ∨ enroll 落盘有效（`store.py:37-46` expiry 校验）。
- enroll 流程（`enroll.py:63-155`）：
  1. `should_run_corpus_auto_enroll`：community_stats 上报开 ∧ community_wanted ∧ auto_enroll ∧ 无手工 env（`enroll.py:63-76`）。
  2. 已有效落盘跳过；**例外**：本机希望贡献但中心策略 `contribute=false` 时强制重登记（防锁死，`enroll.py:71-76`）。
  3. POST `{heartbeat}/corpus/enroll`，payload `{deployment_id}`（多候选：自动模式官方 endpoint 推导，手动模式仅手工 URL）。
  4. 成功 → 落盘 `corpus_community` → `clear_corpus_config_cache()` → `invalidate_shared_context_repository()`（下次取 repo 用新 token 重建）。
  - 启动入口：`packages/pb_stats/startup.py:21` `ensure_corpus_community_enrolled()`（非分片 worker），失败仅告警。
- 401 兜底：`maybe_refresh_corpus_community_enrolled_on_auth_failure`（`community_source.py:99-103` 读 401 → create_task 调度；`enroll.py:147-155`，5 分钟冷却防风暴，`force=True` 忽略有效期）。
- 上传贡献路径四类：①日常学习 mirror（write_fanout，实时异步）②backfill 历史同步（周期渐进）③`/v1/corpus/hot` 快照（仅热词 score，不传消息）④无独立手动提交接口；`community_contribute_enabled` = 本机意图 ∧ 中心 enroll policy。
- on_remote_failure=`local_only`：远端异常跳过该源，非 local 源全失败则返回 merged 到当前为止。

### 联邦（fed）

`fed_enabled` tri-state 判断 + PG 第二连接 `fed_configured()` 合成，但 **fed 读源与写源均未实现**（`factory.build_fed_repository` 恒 None，「联邦 PG 第二连接在后续 Phase 接入」）。`fed_contribute` 恒未达。`docs/common/corpus/README.md` 的「多套牛牛共池」描述的是 federate 跨部署协同（见 [多牛协同面](multi-bot-collaboration.md)），与本处 fed 读源是两个概念。

## 可观测 / WebUI

- **`build_corpus_status_snapshot`**（`status.py:25-161`）：顶层 `composite_active` / `remote_find_mode` / `merge_order` / `merge_strategy` / `on_remote_failure`；`sources.{local,fed,community}` 每源 `enabled/configured/readable/writable`（community 带 `wanted/enrolled/manual/auto_enroll/api_base/contribute/token_present/expires_at/usage`）；`deployment` / `control_plane`。消费方 `packages/pb_webui/stats_dashboard_api.py:200-208` `GET /pallas/api/corpus-status`（cached_read 15s TTL / 90s stale）。OpenAPI：`openspec/pallas-console-v1.json:9545`。
- **usage**（`usage.py`）：`GET {base}/usage` → `{read_lookups, read_hits, contribute_ok, updated_at}`；进程内 120s 缓存 + inflight 去重；401 → re-enroll。
- **WebUI 配置段**：段 ID `corpus_federation`（标题「社区共享接话库」）。**已从通用配置移出**（`env_sections.py:420-452` `_REMOVED_FROM_COMMON_CONFIG_LIST`）**迁到 pb_core 插件配置页**（`packages/pb_core/config.py:47,68-103,199-202` `corpus_federation_payload`/`apply_corpus_federation_patch`）。Phase 1 字段：merge_order（UI 固定 `local,community`/`local`）、merge_strategy、community_enabled、auto_enroll、community_contribute、remote_find_enabled（UI auto/false/prefetch/sync，`true` 归一 prefetch）、community_api_base、community_token + backfill 4 项 + 性能 7 项。fed/on_remote_failure Phase 2 不在 UI。
- **保存热重载**（`apply_corpus_federation_patch`，`corpus_federation_section.py:232-317`）：写 repo settings → `clear_corpus_config_cache()` → remote_find/性能项改则 `invalidate_find_cache(None)` → remote_find 改重启 prefetch workers → 性能改清 reply_perf + snapshot 缓存 → backfill 改 `reload_corpus_backfill_job()` → `invalidate_shared_context_repository()`。
- **慢路径**：`SlowPathTimer`（find 80ms / exists 30ms）；`record_bundle_lookup` / `record_reply_query_stages` / `record_reply_snapshot`；`remote_corpus_budget_snapshot/drain` 进 `pool_diagnostics.py:182-189`；prefetch/mirror 丢弃计数日志限频。

## 热路径与性能（Repeater 接话）

```text
execute_repeater_message (handlers/message.py)
└─ reply_preparation.find_reply_bundle_bounded → bundle_lookup（PALLAS_REPEATER_BUNDLE_TIMEOUT_SEC 0.8s）
   └─ Responder._context_find_with_pool（responder.py:553）
        ├─ 复读同句短路 → 直接回 ReplyBundle
        ├─ pg_pool_under_pressure(0.55) → 跳过
        └─ context_repo.find_by_keywords_for_reply
             ├─ find_cache（TTL 45s，DB fail 负缓存 2s）
             ├─ sync：_find_by_keywords_merged（远程 budget wait=False 竞态放弃）
             └─ prefetch：local 快照 → miss 则 schedule_corpus_prefetch（不阻塞）
```

| 层 | 机制 | 关键参数 |
| --- | --- | --- |
| bundle 层 | TTL 正/负缓存 + inflight 去重 + 超时 | bundle_timeout 0.8s |
| find 层 | 进程内 TTL 缓存 + 单飞 + DB fail 短负缓存 | find_cache 45s / 50000 |
| 本地快照 | PG 限量快照 SQL（≤2 词 6/48，≤3 词 8/64）+ LRU + 独立 timeout | REPLY_* 7 项 |
| 远程 | 池压门禁 0.70 + 并发 semaphore + wait=False 抢槽失败即弃 + multi-base 容错 + 8s 读超时 | REMOTE_* |
| 写回 | 单 worker 队列 2048 + 池压 0.78 丢弃 | 内建 |

两种查询语义：`find_by_keywords`（全量，学习/清理/全源 merge）与 `find_by_keywords_for_reply`（轻量快照，接话用）。

## 启动与懒加载

- **无启动阻塞**：`get_shared_context_repository`（`context_repo_access.py:13-19`）首次被访问才 `make_context_repository()` → `maybe_wrap_composite`（仅存 URL/token 不建连接）；HTTP client 首次使用惰性创建。
- 生命周期绑定点（repeater `startup.py:8-12` + pb_stats startup）：
  - `bind_corpus_prefetch_lifecycle`：startup 仅 mode=prefetch 启 worker。
  - `bind_corpus_backfill_lifecycle`：enabled 时挂 apscheduler。
  - `bind_corpus_write_lifecycle`：`ensure_corpus_write_workers` 首次入队 create_task 拉起单 worker（拉起即不阻塞）。
  - `ensure_corpus_community_enrolled`：pb_stats startup 跑一次，失败不阻塞。
  - `bind_corpus_cleanup_lifecycle`（llm 侧）：污染清理每日任务。

## 禁止与边界

- **写路径不落 fed**：fed 未实现前，所有写只走 local + community mirror；不允许在消息进程同步写语料（必须 work aux 学习后异步）。
- **避免回环**：prefetch 导入走 local insert 不经 mirror；学习 mirror 不触发 prefetch。
- **远程不可靠**：远端读永远可被池压/超时/节流放弃，`local_only` 兜底；热路径不得阻塞等远程。
- **不传隐私**：community 上传一律 group_id=0 去标识化，只含关键词与短句。
- **配置变更要清缓存**：改 `CorpusConfig` / 性能段后必须 `clear_corpus_config_cache()` + 按需 `invalidate_find_cache`，改凭证后 `invalidate_shared_context_repository()`。

## 后续阅读

- [语料联邦（用户/运维面）](../../common/corpus/README.md)
- [横切能力全景](cross-cutting-concerns.md)（perm / limits / storage / reload 声明）
- [多牛协同面](multi-bot-collaboration.md)（federate 跨部署协同，与 fed 语料源区分）
- [LLM 输出链路](llm-output-path.md)（污染防护上游）
- [Repeater 与 LLM 分离](../../guide/llm-and-repeater.md)（语料喂学习队列边界）