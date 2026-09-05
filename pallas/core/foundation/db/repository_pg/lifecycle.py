"""PostgreSQL 引擎 / 会话生命周期与全局状态。

本子模块集中持有跨 Repository 共享的模块级状态
（``_engine``/``_session_factory``、接话快照缓存、``_CONFIG_CACHES``）以及
操作这些状态的函数，保证闭包对全局状态的引用一致。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any

from nonebot import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.repository_pg.schema import Base

# ---------------------------------------------------------------------------
# 运行时 \x00 防御：PostgreSQL TEXT 不接受 NUL 字符，需在写入前统一剥除
# ---------------------------------------------------------------------------


def _s(x: str | None) -> str | None:
    if x is None:
        return None
    return x.replace("\x00", "") if "\x00" in x else x


def _strip_null_deep(obj: Any) -> Any:
    """递归剥除 str / dict / list 中的 \\u0000，用于 JSONB 字段。"""
    if isinstance(obj, str):
        return _s(obj)
    if isinstance(obj, dict):
        return {k: _strip_null_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_null_deep(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# 引擎 / 会话
# ---------------------------------------------------------------------------


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_reply_query_snapshot_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_reply_query_snapshot_inflight: dict[str, asyncio.Task[Any]] = {}
_reply_query_snapshot_lock = asyncio.Lock()


def _ensure_pg_image_cache_blob_data(connection) -> None:
    """旧库 image_cache 仍为 base64_data(TEXT) 时迁到 blob_data(BYTEA)。

    幂等，可重复调用。``create_all`` 不会改已有表列，故升级路径必须走这里。
    """
    insp = _repo.inspect(connection)
    if not insp.has_table("image_cache"):
        return
    names = {c["name"] for c in insp.get_columns("image_cache")}
    if "blob_data" in names and "base64_data" not in names:
        return
    if "blob_data" not in names and "base64_data" not in names:
        connection.execute(text("ALTER TABLE image_cache ADD COLUMN blob_data BYTEA"))
        return
    if "blob_data" not in names:
        connection.execute(text("ALTER TABLE image_cache ADD COLUMN blob_data BYTEA"))
        logger.info("image_cache: 已添加 blob_data 列，开始从 base64_data 迁移")
    if "base64_data" in names:
        connection.execute(
            text(
                "UPDATE image_cache SET blob_data = decode(base64_data, 'base64') "
                "WHERE base64_data IS NOT NULL AND blob_data IS NULL"
            )
        )
        connection.execute(text("ALTER TABLE image_cache DROP COLUMN base64_data"))
        logger.info("image_cache: base64_data → blob_data 迁移完成")


def _ensure_pg_image_cache_content_hash(connection) -> None:
    insp = _repo.inspect(connection)
    if not insp.has_table("image_cache"):
        return
    names = {c["name"] for c in insp.get_columns("image_cache")}
    if "content_hash" not in names:
        connection.execute(text("ALTER TABLE image_cache ADD COLUMN content_hash TEXT"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_image_cache_content_hash ON image_cache (content_hash)"))


def _ensure_pg_image_cache_blob_path(connection) -> None:
    """image_cache 二进制落文件后补 blob_path/blob_size 元数据列。幂等。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("image_cache"):
        return
    names = {c["name"] for c in insp.get_columns("image_cache")}
    if "blob_path" not in names:
        connection.execute(text("ALTER TABLE image_cache ADD COLUMN blob_path TEXT"))
    if "blob_size" not in names:
        connection.execute(text("ALTER TABLE image_cache ADD COLUMN blob_size BIGINT"))


def _ensure_pg_group_config_blocked_user_ids(connection) -> None:
    """旧库 group_config 缺列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "blocked_user_ids" in names:
        return
    connection.execute(text("ALTER TABLE group_config ADD COLUMN blocked_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb"))


def _ensure_pg_background_job_lease_id(connection) -> None:
    insp = _repo.inspect(connection)
    if not insp.has_table("background_job"):
        return
    names = {column["name"] for column in insp.get_columns("background_job")}
    if "lease_id" not in names:
        connection.execute(text("ALTER TABLE background_job ADD COLUMN lease_id TEXT"))
    if "last_error" not in names:
        connection.execute(text("ALTER TABLE background_job ADD COLUMN last_error TEXT"))


def _ensure_pg_group_config_style_profile(connection) -> None:
    """旧库 group_config 缺列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "style_profile" in names:
        return
    connection.execute(text("ALTER TABLE group_config ADD COLUMN style_profile JSONB"))


def _ensure_pg_group_config_plugin_storage(connection) -> None:
    insp = _repo.inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "plugin_storage" in names:
        return
    connection.execute(text("ALTER TABLE group_config ADD COLUMN plugin_storage JSONB NOT NULL DEFAULT '{}'::jsonb"))


def _ensure_pg_group_config_disabled_plugins_audit(connection) -> None:
    """旧库 group_config 缺审计列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "disabled_plugins_audit" in names:
        return
    connection.execute(
        text("ALTER TABLE group_config ADD COLUMN disabled_plugins_audit JSONB NOT NULL DEFAULT '[]'::jsonb")
    )


def _ensure_pg_bot_config_disabled_plugins_audit(connection) -> None:
    """旧库 bot_config 缺审计列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "disabled_plugins_audit" in names:
        return
    connection.execute(
        text("ALTER TABLE bot_config ADD COLUMN disabled_plugins_audit JSONB NOT NULL DEFAULT '[]'::jsonb")
    )


def _ensure_pg_bot_config_persona(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "persona" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN persona JSONB"))


def _ensure_pg_bot_config_community_roster_show_qq(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "community_roster_show_qq" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN community_roster_show_qq BOOLEAN NOT NULL DEFAULT true"))


def _ensure_pg_bot_config_group_style_enabled(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "group_style_enabled" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN group_style_enabled BOOLEAN NOT NULL DEFAULT true"))


def _ensure_pg_user_config_maa_devices(connection) -> None:
    """旧库 user_config 缺列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("user_config"):
        return
    names = {c["name"] for c in insp.get_columns("user_config")}
    if "maa_devices" not in names:
        connection.execute(text("ALTER TABLE user_config ADD COLUMN maa_devices JSONB NOT NULL DEFAULT '{}'::jsonb"))
    if "maa_active_device" not in names:
        connection.execute(text("ALTER TABLE user_config ADD COLUMN maa_active_device TEXT NOT NULL DEFAULT ''"))
    if "maa_stage_plan" not in names:
        connection.execute(text("ALTER TABLE user_config ADD COLUMN maa_stage_plan JSONB NOT NULL DEFAULT '[]'::jsonb"))
    if "plugin_storage" not in names:
        connection.execute(text("ALTER TABLE user_config ADD COLUMN plugin_storage JSONB NOT NULL DEFAULT '{}'::jsonb"))


def _ensure_pg_user_config_ban_audit(connection) -> None:
    """旧库 user_config 缺拉黑审计列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("user_config"):
        return
    names = {c["name"] for c in insp.get_columns("user_config")}
    if "banned_by" not in names:
        connection.execute(text("ALTER TABLE user_config ADD COLUMN banned_by TEXT NOT NULL DEFAULT ''"))
    if "banned_at" not in names:
        connection.execute(text("ALTER TABLE user_config ADD COLUMN banned_at BIGINT NOT NULL DEFAULT 0"))


def _ensure_pg_bot_config_plugin_storage(connection) -> None:
    insp = _repo.inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "plugin_storage" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN plugin_storage JSONB NOT NULL DEFAULT '{}'::jsonb"))


def _ensure_pg_llm_relationship_delta_columns(connection) -> None:
    """旧库 llm_relationship_note 缺人对语气偏置列时补列。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("llm_relationship_note"):
        return
    names = {c["name"] for c in insp.get_columns("llm_relationship_note")}
    if "warmth_delta" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN warmth_delta DOUBLE PRECISION NOT NULL DEFAULT 0")
        )
    if "assertiveness_delta" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN assertiveness_delta DOUBLE PRECISION NOT NULL DEFAULT 0")
        )
    if "affinity" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN affinity DOUBLE PRECISION NOT NULL DEFAULT 0")
        )
    if "rage" not in names:
        connection.execute(text("ALTER TABLE llm_relationship_note ADD COLUMN rage INTEGER NOT NULL DEFAULT 0"))
    if "rage_last_attack_at" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN rage_last_attack_at BIGINT NOT NULL DEFAULT 0")
        )
    if "rage_last_attack_message_id" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN rage_last_attack_message_id BIGINT NOT NULL DEFAULT 0")
        )
    if "rage_silenced_until" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN rage_silenced_until BIGINT NOT NULL DEFAULT 0")
        )
    if "rage_silence_reason" not in names:
        connection.execute(
            text("ALTER TABLE llm_relationship_note ADD COLUMN rage_silence_reason TEXT NOT NULL DEFAULT ''")
        )


def _ensure_pg_llm_memory_embedding_columns(connection) -> None:
    """旧库 llm_memory_entry 缺 embedding 缓存列时补齐。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("llm_memory_entry"):
        return
    names = {c["name"] for c in insp.get_columns("llm_memory_entry")}
    if "embedding_json" not in names:
        connection.execute(text("ALTER TABLE llm_memory_entry ADD COLUMN embedding_json TEXT"))
    if "embedding_model" not in names:
        connection.execute(text("ALTER TABLE llm_memory_entry ADD COLUMN embedding_model TEXT"))


def _ensure_pg_llm_memory_metadata_columns(connection) -> None:
    """旧库 llm_memory_entry 缺治理元数据列时补齐。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("llm_memory_entry"):
        return
    names = {c["name"] for c in insp.get_columns("llm_memory_entry")}
    if "importance" not in names:
        connection.execute(
            text("ALTER TABLE llm_memory_entry ADD COLUMN importance DOUBLE PRECISION NOT NULL DEFAULT 0.5")
        )
    if "confidence" not in names:
        connection.execute(
            text("ALTER TABLE llm_memory_entry ADD COLUMN confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5")
        )
    if "expires_at" not in names:
        connection.execute(text("ALTER TABLE llm_memory_entry ADD COLUMN expires_at BIGINT NOT NULL DEFAULT 0"))
    if "visibility" not in names:
        connection.execute(text("ALTER TABLE llm_memory_entry ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'"))


def _ensure_pg_llm_memory_graph_columns(connection) -> None:
    """旧库记忆图谱表补 soft-delete 列。"""
    insp = _repo.inspect(connection)
    if insp.has_table("llm_memory_entity"):
        names = {c["name"] for c in insp.get_columns("llm_memory_entity")}
        if "deleted_at" not in names:
            connection.execute(text("ALTER TABLE llm_memory_entity ADD COLUMN deleted_at BIGINT"))


def _ensure_pg_message_group_time_index(connection) -> None:
    """message 表补 group_id+time 索引。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_group_time ON message (group_id, time)"))


def _ensure_pg_message_group_user_time_index(connection) -> None:
    """message 表补 group_id+user_id+time 索引。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_message_group_user_time ON message (group_id, user_id, time)")
    )


def _ensure_pg_message_timeline_metadata(connection) -> None:
    """旧 message 表补群时间线所需的身份与引用元数据。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("message"):
        return
    names = {column["name"] for column in insp.get_columns("message")}
    if "sender_name" not in names:
        connection.execute(text("ALTER TABLE message ADD COLUMN sender_name TEXT NOT NULL DEFAULT ''"))
    if "message_id" not in names:
        connection.execute(text("ALTER TABLE message ADD COLUMN message_id BIGINT"))
    if "reply_to_message_id" not in names:
        connection.execute(text("ALTER TABLE message ADD COLUMN reply_to_message_id BIGINT"))
    if "suppressed_by_rage" not in names:
        connection.execute(text("ALTER TABLE message ADD COLUMN suppressed_by_rage BOOLEAN NOT NULL DEFAULT FALSE"))


def _ensure_pg_message_unique_anchor(connection) -> None:
    """message 表补 (group_id, bot_id, message_id) 唯一锚点，落库幂等。

    历史数据在同锚点下可能已重复，先删多余行（保留最小 id）再建唯一约束。
    message_id 为 NULL 的行不参与冲突（PG 中 NULL <> NULL），不受影响。
    """
    insp = _repo.inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(
        text(
            "DELETE FROM message a USING message b "
            "WHERE a.message_id IS NOT NULL "
            "AND b.message_id IS NOT NULL "
            "AND a.group_id = b.group_id "
            "AND a.bot_id = b.bot_id "
            "AND a.message_id = b.message_id "
            "AND a.id > b.id"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_message_group_bot_message_id "
            "ON message (group_id, bot_id, message_id)"
        )
    )


def _ensure_pg_context_answer_reply_index(connection) -> None:
    """context_answer 表补 context_id+count+time 索引。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("context_answer"):
        return
    connection.execute(text("DROP INDEX IF EXISTS ix_context_answer_context_id"))
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_context_answer_ctx_count_time ON context_answer (context_id, count, time)")
    )


def _ensure_pg_context_answer_message_reply_index(connection) -> None:
    """context_answer_message 表补 answer_id+id 索引。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("context_answer_message"):
        return
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_context_answer_message_answer_id_id "
            "ON context_answer_message (answer_id, id)"
        )
    )


def _ensure_pg_background_job_delivery_claim_index(connection) -> None:
    """background_job 表补已完成视觉投递领取索引。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("background_job"):
        return
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_job_delivery_claim ON background_job (kind, status, finished_at)"
        )
    )


def _ensure_pg_background_job_pending_claim_index(connection) -> None:
    """background_job 表补 pending 领取部分索引，避免 claim 扫全部历史 available 行。"""
    insp = _repo.inspect(connection)
    if not insp.has_table("background_job"):
        return
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_background_job_pending_claim "
            "ON background_job (available_at, created_at) "
            "WHERE status = 'pending' AND finished_at IS NULL"
        )
    )


def _ensure_pg_stat_statements_extension(connection) -> None:
    """启用 pg_stat_statements（仅应在独立 autocommit 连接中调用）。

    勿放在 schema 迁移同一事务内：非超级用户失败会污染事务，导致整次 init 回滚。
    """
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))


async def try_enable_pg_stat_statements(engine: AsyncEngine) -> bool:
    """可选诊断扩展：独立短事务，失败回滚本事务且不阻断启动。"""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_ensure_pg_stat_statements_extension)
        return True
    except Exception as exc:
        logger.warning(
            "数据库：跳过 pg_stat_statements（需扩展权限或 shared_preload_libraries），诊断将降级。详情: {}",
            exc,
        )
        return False


def is_pg_initialized() -> bool:
    return _session_factory is not None


def pg_engine() -> AsyncEngine | None:
    return _engine


def pg_pool_live_stats() -> dict[str, int] | None:
    """运行时连接池占用。"""
    if _engine is None:
        return None
    from pallas.core.foundation.db.pool_budget import pg_pool_capacity

    pool = _engine.pool
    return {
        "pool_size": int(pool.size()),
        "checked_out": int(pool.checkedout()),
        "overflow": int(pool.overflow()),
        "capacity": pg_pool_capacity(),
    }


@asynccontextmanager
async def get_session(*, read_only: bool = False):
    if _session_factory is None:
        raise RuntimeError("PostgreSQL 尚未初始化，请先调用 init_pg()")
    from pallas.core.foundation.db.pool_diagnostics import (
        note_slow_pg_session,
        pg_session_caller_hint_entry,
        session_hold_warn_ms,
    )

    caller = pg_session_caller_hint_entry()
    session = _session_factory()
    # 只读路径用 AUTOCOMMIT：多段 SELECT 之间不会长期占着 idle in transaction 连接。
    if read_only:
        await session.connection(execution_options={"isolation_level": "AUTOCOMMIT"})
    t0 = time.monotonic()
    try:
        yield session
    except BaseException:
        # CancelledError 非 Exception 子类；清理须 shield，避免 close/rollback 再被取消导致连接未归还池
        if not read_only:
            with contextlib.suppress(BaseException):
                await asyncio.shield(session.rollback())
        raise
    finally:
        held_ms = (time.monotonic() - t0) * 1000.0
        if held_ms >= session_hold_warn_ms():
            note_slow_pg_session(held_ms, caller)
        try:
            if not read_only:
                with contextlib.suppress(BaseException):
                    await asyncio.shield(session.rollback())
            await asyncio.shield(session.close())
        except BaseException:
            with contextlib.suppress(BaseException):
                await asyncio.shield(session.invalidate())


# 启动期 DDL ensure 注册表（step_id 稳定，供控制台与可观测使用）
PG_SCHEMA_ENSURE_STEPS: list[tuple[str, Any]] = [
    ("ddl.image_cache_blob_data", _ensure_pg_image_cache_blob_data),
    ("ddl.image_cache_content_hash", _ensure_pg_image_cache_content_hash),
    ("ddl.image_cache_blob_path", _ensure_pg_image_cache_blob_path),
    ("ddl.group_config_blocked_user_ids", _ensure_pg_group_config_blocked_user_ids),
    ("ddl.background_job_lease_id", _ensure_pg_background_job_lease_id),
    ("ddl.group_config_style_profile", _ensure_pg_group_config_style_profile),
    ("ddl.group_config_plugin_storage", _ensure_pg_group_config_plugin_storage),
    ("ddl.group_config_disabled_plugins_audit", _ensure_pg_group_config_disabled_plugins_audit),
    ("ddl.bot_config_disabled_plugins_audit", _ensure_pg_bot_config_disabled_plugins_audit),
    ("ddl.bot_config_community_roster_show_qq", _ensure_pg_bot_config_community_roster_show_qq),
    ("ddl.bot_config_group_style_enabled", _ensure_pg_bot_config_group_style_enabled),
    ("ddl.bot_config_persona", _ensure_pg_bot_config_persona),
    ("ddl.bot_config_plugin_storage", _ensure_pg_bot_config_plugin_storage),
    ("ddl.user_config_maa_devices", _ensure_pg_user_config_maa_devices),
    ("ddl.user_config_ban_audit", _ensure_pg_user_config_ban_audit),
    ("ddl.llm_memory_embedding_columns", _ensure_pg_llm_memory_embedding_columns),
    ("ddl.llm_memory_metadata_columns", _ensure_pg_llm_memory_metadata_columns),
    ("ddl.llm_memory_graph_columns", _ensure_pg_llm_memory_graph_columns),
    ("ddl.llm_relationship_delta_columns", _ensure_pg_llm_relationship_delta_columns),
    ("ddl.message_group_time_index", _ensure_pg_message_group_time_index),
    ("ddl.message_group_user_time_index", _ensure_pg_message_group_user_time_index),
    ("ddl.message_timeline_metadata", _ensure_pg_message_timeline_metadata),
    ("ddl.message_unique_anchor", _ensure_pg_message_unique_anchor),
    ("ddl.context_answer_reply_index", _ensure_pg_context_answer_reply_index),
    ("ddl.context_answer_message_reply_index", _ensure_pg_context_answer_message_reply_index),
    ("ddl.background_job_delivery_claim_index", _ensure_pg_background_job_delivery_claim_index),
    ("ddl.background_job_pending_claim_index", _ensure_pg_background_job_pending_claim_index),
]


async def init_pg(engine: AsyncEngine) -> None:
    """创建表结构并注入 engine；对已有 PG 库补全 group_config.blocked_user_ids 等轻量迁移。"""
    global _engine, _session_factory
    from pallas.core.foundation.db.schema_registry import run_registered_pg_ensures

    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_registered_pg_ensures)


async def dispose_pg() -> None:
    """关闭连接池并清空配置 TTL 缓存，bot 退出或测试 teardown 时调用。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    # 释放 engine 后清空 session factory
    _session_factory = None
    await clear_reply_query_snapshot_cache(None)
    # schema 重建后清空 ORM 缓存
    for cache in _CONFIG_CACHES.values():
        await cache.clear()


# ---------------------------------------------------------------------------
# 接话快照缓存
# ---------------------------------------------------------------------------

_CONFIG_CACHES: dict[type, Any] = {}


async def clear_reply_query_snapshot_cache(keywords: str | None = None) -> None:
    async with _reply_query_snapshot_lock:
        if keywords is None:
            _reply_query_snapshot_cache.clear()
            _reply_query_snapshot_inflight.clear()
            return
        key = keywords.strip()
        if key:
            _reply_query_snapshot_cache.pop(key, None)


async def cached_reply_query_snapshot(
    keywords: str,
    loader,
) -> Any:
    from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure
    from pallas.core.platform.ingress.hotpath_metrics import record_reply_snapshot
    from pallas.product.corpus.find_cache import mark_reply_db_fail, reply_db_fail_active
    from pallas.product.corpus.reply_perf_config import (
        reply_snapshot_max_entries,
        reply_snapshot_query_timeout_sec,
        reply_snapshot_ttl_sec,
    )

    key = (keywords or "").strip()
    if not key:
        return None
    if pg_pool_under_pressure(threshold=0.55):
        record_reply_snapshot(hit=False, skipped=True)
        logger.debug(
            "Reply query snapshot skipped because the PostgreSQL pool is under pressure for keyword length [{}].",
            len(key),
        )
        return None
    if reply_db_fail_active(key):
        record_reply_snapshot(hit=False, skipped=True)
        logger.debug(
            "Reply query snapshot skipped during database-failure cooldown for keyword length [{}].",
            len(key),
        )
        return None
    now = time.monotonic()
    task: asyncio.Task[Any] | None = None
    async with _reply_query_snapshot_lock:
        hit = _reply_query_snapshot_cache.get(key)
        if hit is not None:
            expire_at, value = hit
            if now < expire_at:
                _reply_query_snapshot_cache.move_to_end(key)
                record_reply_snapshot(hit=True)
                return value
            _reply_query_snapshot_cache.pop(key, None)
        task = _reply_query_snapshot_inflight.get(key)
        if task is None:
            task = asyncio.create_task(loader(key))
            _reply_query_snapshot_inflight[key] = task
            record_reply_snapshot(hit=False)
        else:
            # 与 inflight 合并：算命中同类请求，避免重复打库计数偏高
            record_reply_snapshot(hit=True)

    try:
        ctx = await asyncio.wait_for(asyncio.shield(task), timeout=reply_snapshot_query_timeout_sec())
    except TimeoutError:
        async with _reply_query_snapshot_lock:
            if _reply_query_snapshot_inflight.get(key) is task:
                _reply_query_snapshot_inflight.pop(key, None)
        record_reply_snapshot(hit=False)
        logger.debug("Reply query snapshot timed out for keyword length [{}].", len(key))
        return None
    except Exception as exc:
        async with _reply_query_snapshot_lock:
            if _reply_query_snapshot_inflight.get(key) is task:
                _reply_query_snapshot_inflight.pop(key, None)
        if is_pg_pool_timeout_error(exc):
            mark_reply_db_fail(key)
            logger.debug(
                "Reply query snapshot skipped after a database timeout for keyword length [{}].",
                len(key),
            )
            return None
        raise

    async with _reply_query_snapshot_lock:
        if _reply_query_snapshot_inflight.get(key) is task:
            _reply_query_snapshot_inflight.pop(key, None)
        _reply_query_snapshot_cache[key] = (time.monotonic() + reply_snapshot_ttl_sec(), ctx)
        _reply_query_snapshot_cache.move_to_end(key)
        while len(_reply_query_snapshot_cache) > reply_snapshot_max_entries():
            _reply_query_snapshot_cache.popitem(last=False)
    return ctx


async def vacuum_message_table() -> None:
    """语料扫库批量删除后回收 message 表死元组，缓解 autovacuum 滞后导致的索引膨胀。

    VACUUM 不能运行在事务块内，需借用 AUTOCOMMIT 连接；失败仅降级不影响主流程。
    """
    if _engine is None:
        return
    try:
        async with _engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT").exec_driver_sql("VACUUM message")
    except Exception as exc:
        logger.warning("vacuum message failed, degraded: {}", exc)
