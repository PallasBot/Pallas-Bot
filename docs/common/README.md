# `src/common` 共用模块

插件共享的基础设施：数据库、入站门控、WebUI 通用配置、权限、工具等。
**WebUI「通用配置」** 由 `src/common/webui/env_sections.py` 注册，写入根目录 `.env` 后按段触发热重载（见下表）。

实现代码在 [`src/common/`](../../src/common/)；子目录专题文档见本页「相关文档」。

## 目录分类

| 分类 | 路径 | 职责 |
|------|------|------|
| **数据库** | `db/` | 多后端 Repository、PG ORM、`pg_runtime_config`（连接池/配置行缓存） |
| **入站门控** | `ingress/` | 多牛分片、fast lane、慢路径限流、Notice 采样、`matcher_priority` |
| **黑名单快照** | `ban_gate/` | 全量拉黑/本群屏蔽内存表，周期对齐 DB |
| **多 Bot 群消息** | `multi_bot/` | 去重、抢占、跨进程 claim（`dedup` / `claim`） |
| **运行时配置** | `config/` | `BotConfig` / `GroupConfig` / `UserConfig` 读写（走 DB，非 WebUI 段） |
| **命令权限** | `cmd_perm/` | 等级校验、WebUI 覆盖 |
| **消息审查** | `message_scrub/` | 入站过滤、词库、第三方审查 API |
| **WebUI 共用** | `webui/` | 通用配置段、插件热重载注册表 |
| **控制台登录** | `pallas_console_login.py`、`pallas_login_page.py` | 控制台鉴权页 |
| **日志 / Web** | `logging/`、`web/` | loguru 桥接、Bot Web 辅助 |
| **路径** | `paths/` | `data/`、插件数据目录 |
| **环境文件** | `env_dotenv.py` | 读写 `.env`、合并层 |
| **服务探测** | `service_probe/` | HTTP 探活 |
| **明日方舟共用** | `arknights/`、`arknights_skill_text.py` | 决斗资源同步等 |
| **工具** | `utils/` | CQ 码、媒体缓存、下载等 |

插件专属逻辑在 `src/plugins/<name>/`。

## WebUI「通用配置」段与热重载

保存后都会 **`upsert_env_dotenv_items` 写 `.env`**。

| WebUI 段 ID | 标题 | 环境变量前缀 | 保存后 |
|-------------|------|--------------|--------|
| `ingress` | 入站门控 / Fast Lane | `PALLAS_INGRESS_*`、`PALLAS_NOTICE_*` | **立即**：重读配置、`reload_ingress_dispatch_runtime()`（慢路径槽 + 水群 dispatch worker） |
| `ban_gate_snapshot` | 黑名单门禁快照 | `PALLAS_BAN_*` | **立即**：清配置缓存并触发一次全量刷新；`stale`/`gate_db_timeout` 下次读生效 |
| `pg_runtime` | PostgreSQL 连接池 / 配置缓存 | `PG_POOL_*`、`PG_CONFIG_CACHE_*` | **部分**：`config_cache_*` 立即；**`pool_*` 须重启 Bot** |
| `message_scrub` | 消息审查 / 入站过滤 | `PALLAS_SCRUB_*` 等 | **立即**：`reload_message_scrub_caches()` |
| `cmd_perm` | 命令权限 | `PALLAS_COMMAND_PERMISSION_OVERRIDES` | **立即** |
| 各插件段 | 见控制台列表 | 字段名大写或段内映射 | **立即**（`install_hot_reload_config` 的插件） |

### 须改 `.env` 并重启 Bot 的项

`DB_BACKEND`、`PG_HOST`、`PG_USER`、`PG_PASSWORD`、`PG_DB`、`HOST`/`PORT`、`SUPERUSERS` 等启动时建连/驱动配置。

### 黑名单快照：即时 vs 周期

- **命令拉黑/解禁**：`patch_user_banned` / `patch_group_blocked_users` → 内存立即更新。
- **WebUI 改间隔/超时**：名单仍靠周期刷新或命令 `patch_*`；保存后会额外 `refresh_ban_gate_snapshot()` 一次。
- **快照过期**：热路径回退 DB，超时见 `gate_db_timeout_sec`。

### 入站门控

- **dispatch 入口分片**：多牛同群在进 `handle_event` 前仅赢家 bot 继续（greeting 全员同响除外）。
- 预处理顺序：Notice → **分片（兜底）** → **慢路径**（仅通过分片的非 fast lane 水群）→ 水群 **dispatch 队列**（worker 默认 `min(主槽, 24)`，可配 `ingress_slow_dispatch_workers`）。
- 命令 / 私聊 / `牛牛*` 前缀等 **Fast Lane** 不占慢路径槽、不经水群队列，**异步**调度 `handle_event`。
- `get_ingress_config()` 进程内缓存；WebUI「通用配置 → 入站门控」保存后写 `.env` 并热重载，**无需重启 Bot**。
- 单进程稳态推荐（可在 WebUI 调整）：`ingress_slow_drop_on_timeout=false`，`ingress_slow_overflow_concurrency=32～48`，`ingress_slow_concurrency=16～24`（多牛同群按群量酌增）。

## 代码入口

| 能力 | 入口 |
|------|------|
| 通用配置段列表 | `webui/env_sections.py` → `list_webui_env_sections()` |
| 保存 PATCH | `apply_webui_env_section_patch()` |
| 插件配置热重载 | `webui/plugin_config.py` → `install_hot_reload_config()` |
| PG 连接池 | `db/__init__.py` → `init_postgresql_db()` |
| 黑名单快照任务 | `bot.py` → `ban_gate.start_ban_gate_snapshot()` |
| 多牛抢占（插件） | `from src.common.multi_bot import claim_group_handler` |

## 相关文档

| 文档 | 说明 |
|------|------|
| [cmd_perm](./cmd_perm/README.md) | 命令权限 |
| [message_scrub](./message_scrub/README.md) | 消息审查 |
| [webui](./webui/README.md) | 控制台配置热重载 |

## 新增 WebUI 配置段 checklist

1. 增加 `XxxConfig` + `from_env` / `get_*` / `clear_*_cache`（可放在子包 `config.py`）。
2. 在 `webui/env_sections.py` 注册段。
3. 在 `apply_webui_env_section_patch()` 中调用 `clear_*` / `reload_*`。
4. `Field(description=...)` 写清是否需重启与推荐取值。
