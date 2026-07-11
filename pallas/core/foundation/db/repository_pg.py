"""PostgreSQL Repository 实现"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from nonebot import logger
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    delete,
    func,
    insert,
    inspect,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from pallas.core.platform.observability import slow_path_threshold_ms
from pallas.product.llm.corpus_contamination import reject_corpus_learn_message

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import Answer, Ban, Context, ImageCache, Message

_JsonB = JSONB().with_variant(JSON(), "sqlite")


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
# ORM 定义
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class ContextAnswerRow(Base):
    __tablename__ = "context_answer"
    # keywords_hash 定长 md5 唯一索引
    __table_args__ = (
        UniqueConstraint("context_id", "group_id", "keywords_hash", name="uq_context_answer_ctx_group_kw"),
        Index("ix_context_answer_ctx_count_time", "context_id", "count", "time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_hash: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    messages: Mapped[list[ContextAnswerMessageRow]] = relationship(
        "ContextAnswerMessageRow", cascade="all, delete-orphan", lazy="noload"
    )


class ContextAnswerMessageRow(Base):
    __tablename__ = "context_answer_message"
    __table_args__ = (Index("ix_context_answer_message_answer_id_id", "answer_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("context_answer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ContextBanRow(Base):
    __tablename__ = "context_ban"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class ContextRow(Base):
    __tablename__ = "context"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    # unique=True 已由 PG 自动建 btree，不再附加 index=True 以免冗余索引
    keywords_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    clear_time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    answers: Mapped[list[ContextAnswerRow]] = relationship(
        "ContextAnswerRow", cascade="all, delete-orphan", lazy="noload"
    )
    ban: Mapped[list[ContextBanRow]] = relationship("ContextBanRow", cascade="all, delete-orphan", lazy="noload")


class MessageRow(Base):
    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_time", "time"),
        Index("ix_message_group_time", "group_id", "time"),
        Index("ix_message_group_user_time", "group_id", "user_id", "time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    is_plain_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class BlackListRow(Base):
    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    answers: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    answers_reserve: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)


class AdminMemberRow(Base):
    __tablename__ = "admin_members"
    __table_args__ = (
        UniqueConstraint("scope", "bot_id", "user_id", name="uq_admin_members_scope_bot_user"),
        Index("ix_admin_members_bot_user", "bot_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PallasACLRow(Base):
    __tablename__ = "acl_rules"
    __table_args__ = (
        UniqueConstraint(
            "role",
            "subject",
            "action",
            "target_scope",
            "target",
            name="uq_acl_rules_signature",
        ),
        Index("ix_acl_rules_action", "action"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_scope: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class SchemaMigrationRow(Base):
    __tablename__ = "schema_migrations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    step: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    applied_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class BotConfigRow(Base):
    __tablename__ = "bot_config"

    account: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    admins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    auto_accept_friend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_accept_group: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    security: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    taken_name: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    drunk: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    community_roster_show_qq: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    persona: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    group_style_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    plugin_storage: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)


class GroupConfigRow(Base):
    __tablename__ = "group_config"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    roulette_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sing_progress: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    blocked_user_ids: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    style_profile: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    plugin_storage: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)


class UserConfigRow(Base):
    __tablename__ = "user_config"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maa_devices: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    maa_active_device: Mapped[str] = mapped_column(Text, nullable=False, default="")
    maa_stage_plan: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    plugin_storage: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)


class ImageCacheRow(Base):
    __tablename__ = "image_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cq_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # 改为原生二进制：PG DDL 为 BYTEA。Text → LargeBinary 是一次性破坏性变更，
    # 历史数据由 tools/migrate_image_cache_to_bytea.py 负责（PG 侧执行
    # ALTER TABLE ... TYPE BYTEA USING decode(base64_data, 'base64')）。
    blob_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ref_times: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    date: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)


class LlmChatMessageRow(Base):
    __tablename__ = "llm_chat_message"
    __table_args__ = (
        Index("ix_llm_chat_message_bot_group_time", "bot_id", "group_id", "created_at"),
        Index("ix_llm_chat_message_bot_group_user_time", "bot_id", "group_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmMemoryEntryRow(Base):
    __tablename__ = "llm_memory_entry"
    __table_args__ = (Index("ix_llm_memory_entry_bot_group_time", "bot_id", "group_id", "updated_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="teach")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LlmRelationshipNoteRow(Base):
    """关系备注层：按 (bot, group, user) 维护稳定关系事实，带置信权重与衰减。"""

    __tablename__ = "llm_relationship_note"
    __table_args__ = (
        Index(
            "ix_llm_relationship_note_scope",
            "bot_id",
            "group_id",
            "user_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="teach")
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


# ---------------------------------------------------------------------------
# 引擎 / 会话
# ---------------------------------------------------------------------------


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_reply_query_snapshot_cache: OrderedDict[str, tuple[float, Context | None]] = OrderedDict()
_reply_query_snapshot_inflight: dict[str, asyncio.Task[Context | None]] = {}
_reply_query_snapshot_lock = asyncio.Lock()
_DELETE_ID_BATCH = 1000


def _ensure_pg_group_config_blocked_user_ids(connection) -> None:
    """旧库 group_config 缺列时补列。"""
    insp = inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "blocked_user_ids" in names:
        return
    connection.execute(text("ALTER TABLE group_config ADD COLUMN blocked_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb"))


def _ensure_pg_group_config_style_profile(connection) -> None:
    """旧库 group_config 缺列时补列。"""
    insp = inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "style_profile" in names:
        return
    connection.execute(text("ALTER TABLE group_config ADD COLUMN style_profile JSONB"))


def _ensure_pg_group_config_plugin_storage(connection) -> None:
    insp = inspect(connection)
    if not insp.has_table("group_config"):
        return
    names = {c["name"] for c in insp.get_columns("group_config")}
    if "plugin_storage" in names:
        return
    connection.execute(text("ALTER TABLE group_config ADD COLUMN plugin_storage JSONB NOT NULL DEFAULT '{}'::jsonb"))


def _ensure_pg_bot_config_persona(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "persona" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN persona JSONB"))


def _ensure_pg_bot_config_community_roster_show_qq(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "community_roster_show_qq" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN community_roster_show_qq BOOLEAN NOT NULL DEFAULT true"))


def _ensure_pg_bot_config_group_style_enabled(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "group_style_enabled" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN group_style_enabled BOOLEAN NOT NULL DEFAULT true"))


def _ensure_pg_user_config_maa_devices(connection) -> None:
    """旧库 user_config 缺列时补列。"""
    insp = inspect(connection)
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


def _ensure_pg_bot_config_plugin_storage(connection) -> None:
    insp = inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "plugin_storage" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN plugin_storage JSONB NOT NULL DEFAULT '{}'::jsonb"))


def _ensure_pg_message_group_time_index(connection) -> None:
    """message 表补 group_id+time 索引。"""
    insp = inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_group_time ON message (group_id, time)"))


def _ensure_pg_message_group_user_time_index(connection) -> None:
    """message 表补 group_id+user_id+time 索引。"""
    insp = inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_message_group_user_time ON message (group_id, user_id, time)")
    )


def _ensure_pg_context_answer_reply_index(connection) -> None:
    """context_answer 表补 context_id+count+time 索引。"""
    insp = inspect(connection)
    if not insp.has_table("context_answer"):
        return
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_context_answer_ctx_count_time ON context_answer (context_id, count, time)")
    )


def _ensure_pg_context_answer_message_reply_index(connection) -> None:
    """context_answer_message 表补 answer_id+id 索引。"""
    insp = inspect(connection)
    if not insp.has_table("context_answer_message"):
        return
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_context_answer_message_answer_id_id "
            "ON context_answer_message (answer_id, id)"
        )
    )


def _ensure_pg_stat_statements_extension(connection) -> None:
    """启用 pg_stat_statements。失败时降级为仅无该视图的诊断。"""
    try:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
    except Exception:
        # 例如服务端未配置 shared_preload_libraries；保持启动成功，由诊断层输出 unavailable。
        pass


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


async def init_pg(engine: AsyncEngine) -> None:
    """创建表结构并注入 engine；对已有 PG 库补全 group_config.blocked_user_ids 等轻量迁移。"""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_pg_group_config_blocked_user_ids)
        await conn.run_sync(_ensure_pg_group_config_style_profile)
        await conn.run_sync(_ensure_pg_group_config_plugin_storage)
        await conn.run_sync(_ensure_pg_bot_config_community_roster_show_qq)
        await conn.run_sync(_ensure_pg_bot_config_group_style_enabled)
        await conn.run_sync(_ensure_pg_bot_config_persona)
        await conn.run_sync(_ensure_pg_bot_config_plugin_storage)
        await conn.run_sync(_ensure_pg_user_config_maa_devices)
        await conn.run_sync(_ensure_pg_message_group_time_index)
        await conn.run_sync(_ensure_pg_message_group_user_time_index)
        await conn.run_sync(_ensure_pg_context_answer_reply_index)
        await conn.run_sync(_ensure_pg_context_answer_message_reply_index)
        await conn.run_sync(_ensure_pg_stat_statements_extension)


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


_LOAD_RELATED = [
    selectinload(ContextRow.answers).selectinload(ContextAnswerRow.messages),
    selectinload(ContextRow.ban),
]

_LOAD_REPLY_CTX = [
    selectinload(ContextRow.ban),
]


def keywords_hash(keywords: str) -> str:
    # 先剥除 \x00 再哈希，与 ContextRow.keywords 实际存储值保持一致
    clean = keywords.replace("\x00", "") if keywords and "\x00" in keywords else keywords
    return hashlib.md5((clean or "").encode("utf-8", errors="replace")).hexdigest()


# asyncpg 单语句参数上限 32767
_ANSWER_BATCH = 500  # ContextAnswerRow 6 列 × 500 = 3000
_MSG_BATCH = 16000  # ContextAnswerMessageRow 2 列 × 16000 = 32000


async def delete_context_answer_orphans(
    session: AsyncSession,
    *,
    ctx_id: int,
    kept_ids: list[int],
    chunk_size: int = _DELETE_ID_BATCH,
) -> None:
    """删除指定 Context 下未保留的 Answer，避免生成超长 NOT IN 参数列表。"""
    if not kept_ids:
        await session.execute(delete(ContextAnswerRow).where(ContextAnswerRow.context_id == ctx_id))
        return

    existing_ids = (
        (await session.execute(select(ContextAnswerRow.id).where(ContextAnswerRow.context_id == ctx_id)))
        .scalars()
        .all()
    )
    kept_id_set = set(kept_ids)
    orphan_ids = [int(ans_id) for ans_id in existing_ids if int(ans_id) not in kept_id_set]
    for offset in range(0, len(orphan_ids), chunk_size):
        chunk = orphan_ids[offset : offset + chunk_size]
        await session.execute(
            delete(ContextAnswerRow).where(ContextAnswerRow.context_id == ctx_id, ContextAnswerRow.id.in_(chunk))
        )


_BAN_BATCH = 6000  # ContextBanRow 5 列 × 6000 = 30000


async def _insert_answers_batched(session: AsyncSession, context_id: int, answers) -> None:
    """分批插入 ContextAnswerRow 及其关联的 ContextAnswerMessageRow"""

    for i in range(0, len(answers), _ANSWER_BATCH):
        batch: list[Answer] = answers[i : i + _ANSWER_BATCH]
        rows = []
        for a in batch:
            kw = _s(a.keywords) or ""
            rows.append(
                ContextAnswerRow(
                    context_id=context_id,
                    keywords=kw,
                    keywords_hash=keywords_hash(kw),
                    group_id=a.group_id,
                    count=a.count,
                    time=a.time,
                )
            )
        session.add_all(rows)
        await session.flush()

        msg_rows = [
            ContextAnswerMessageRow(answer_id=rows[j].id, message=_s(m) or "")
            for j, a in enumerate(batch)
            for m in a.messages
        ]
        for k in range(0, len(msg_rows), _MSG_BATCH):
            session.add_all(msg_rows[k : k + _MSG_BATCH])
            await session.flush()


async def _insert_bans_batched(session: AsyncSession, context_id: int, bans) -> None:
    """分批插入 ContextBanRow"""
    for i in range(0, len(bans), _BAN_BATCH):
        batch = bans[i : i + _BAN_BATCH]
        session.add_all([
            ContextBanRow(
                context_id=context_id,
                keywords=_s(b.keywords) or "",
                group_id=b.group_id,
                reason=_s(b.reason) or "",
                time=b.time,
            )
            for b in batch
        ])
        await session.flush()


def row_to_context(row: ContextRow, *, reply_messages: dict[int, list[str]] | None = None) -> Context:
    from pallas.core.foundation.db.modules import Answer, Ban, Context

    answers = []
    for a in row.answers:
        if reply_messages is not None:
            msgs = list(reply_messages.get(int(a.id), []))
        else:
            msgs = [m.message for m in a.messages]
        answers.append(
            Answer.model_construct(
                keywords=a.keywords,
                group_id=a.group_id,
                count=a.count,
                time=a.time,
                messages=msgs,
            )
        )
    ban = [
        Ban.model_construct(
            keywords=b.keywords,
            group_id=b.group_id,
            reason=b.reason,
            time=b.time,
        )
        for b in row.ban
    ]
    return Context.model_construct(
        keywords=row.keywords,
        time=row.time,
        trigger_count=row.trigger_count,
        answers=answers,
        ban=ban,
        clear_time=row.clear_time,
    )


def build_reply_context(
    *,
    keywords: str,
    time_value: int,
    trigger_count: int,
    clear_time: int,
    answer_rows: list[ContextAnswerRow],
    ban_rows: list[ContextBanRow],
    reply_messages: dict[int, list[str]],
):
    from pallas.core.foundation.db.modules import Answer, Ban, Context

    return Context.model_construct(
        keywords=keywords,
        time=time_value,
        trigger_count=trigger_count,
        answers=[
            Answer.model_construct(
                keywords=answer.keywords,
                group_id=answer.group_id,
                count=answer.count,
                time=answer.time,
                messages=list(reply_messages.get(int(answer.id), [])),
            )
            for answer in answer_rows
        ],
        ban=[
            Ban.model_construct(
                keywords=ban.keywords,
                group_id=ban.group_id,
                reason=ban.reason,
                time=ban.time,
            )
            for ban in ban_rows
        ],
        clear_time=clear_time,
    )


def build_reply_message_query(answer_ids: list[int], msg_cap: int):
    rn = (
        func
        .row_number()
        .over(
            partition_by=ContextAnswerMessageRow.answer_id,
            order_by=ContextAnswerMessageRow.id.desc(),
        )
        .label("rn")
    )
    ranked = (
        select(
            ContextAnswerMessageRow.answer_id,
            ContextAnswerMessageRow.message,
            ContextAnswerMessageRow.id,
            rn,
        )
        .where(ContextAnswerMessageRow.answer_id.in_(answer_ids))
        .subquery()
    )
    return (
        select(ranked.c.answer_id, ranked.c.message, ranked.c.id)
        .where(ranked.c.rn <= msg_cap)
        .order_by(ranked.c.answer_id, ranked.c.id)
    )


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
) -> Context | None:
    from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure
    from pallas.product.corpus.find_cache import mark_reply_db_fail, reply_db_fail_active
    from pallas.product.corpus.reply_perf_config import reply_snapshot_max_entries, reply_snapshot_ttl_sec

    key = (keywords or "").strip()
    if not key:
        return None
    if pg_pool_under_pressure(threshold=0.55):
        logger.debug(
            "reply_query_snapshot.skip pg_pool_pressure kw_len={}",
            len(key),
        )
        return None
    if reply_db_fail_active(key):
        logger.debug(
            "reply_query_snapshot.skip reply_db_fail_cooldown kw_len={}",
            len(key),
        )
        return None
    now = time.monotonic()
    task: asyncio.Task[Context | None] | None = None
    async with _reply_query_snapshot_lock:
        hit = _reply_query_snapshot_cache.get(key)
        if hit is not None:
            expire_at, value = hit
            if now < expire_at:
                _reply_query_snapshot_cache.move_to_end(key)
                return value
            _reply_query_snapshot_cache.pop(key, None)
        task = _reply_query_snapshot_inflight.get(key)
        if task is None:
            task = asyncio.create_task(loader(key))
            _reply_query_snapshot_inflight[key] = task

    try:
        ctx = await asyncio.shield(task)
    except Exception as exc:
        async with _reply_query_snapshot_lock:
            if _reply_query_snapshot_inflight.get(key) is task:
                _reply_query_snapshot_inflight.pop(key, None)
        if is_pg_pool_timeout_error(exc):
            mark_reply_db_fail(key)
            logger.debug(
                "reply_query_snapshot.skip db_timeout kw_len={}",
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


def row_to_blacklist(row: BlackListRow):
    from pallas.core.foundation.db.modules import BlackList

    return BlackList.model_construct(
        group_id=row.group_id,
        answers=list(row.answers),
        answers_reserve=list(row.answers_reserve),
    )


def row_to_image_cache(row: ImageCacheRow) -> ImageCache:
    from pallas.core.foundation.db.modules import ImageCache

    return ImageCache.model_construct(
        cq_code=row.cq_code,
        blob_data=row.blob_data,
        ref_times=row.ref_times,
        date=row.date,
    )


class PgContextRepository:
    async def context_exists_by_keywords(self, keywords: str) -> bool:
        khash = keywords_hash(keywords)
        async with get_session(read_only=True) as session:
            result = await session.execute(select(ContextRow.id).where(ContextRow.keywords_hash == khash).limit(1))
            return result.scalar_one_or_none() is not None

    async def find_by_keywords(self, keywords: str) -> Context | None:
        khash = keywords_hash(keywords)
        async with get_session(read_only=True) as session:
            result = await session.execute(
                select(ContextRow).options(*_LOAD_RELATED).where(ContextRow.keywords_hash == khash)
            )
            row = result.scalar_one_or_none()
            return row_to_context(row) if row else None

    async def find_by_keywords_for_reply(self, keywords: str) -> Context | None:
        return await cached_reply_query_snapshot(keywords, self._find_by_keywords_for_reply_uncached)

    async def _find_by_keywords_for_reply_uncached(self, keywords: str) -> Context | None:
        """接话路径：轻量列查询 + 限量 Answer/Message，避免 ORM 关联热路径放大。"""
        khash = keywords_hash(keywords)
        from pallas.product.corpus.reply_perf_config import reply_query_caps

        msg_cap, ans_cap = reply_query_caps(keywords)
        t_start = time.monotonic()
        t_context_ms = 0.0
        t_ban_ms = 0.0
        t_answer_ms = 0.0
        t_message_ms = 0.0
        ban_count = 0
        answer_count = 0
        message_count = 0
        async with get_session(read_only=True) as session:
            t0 = time.monotonic()
            result = await session.execute(
                select(
                    ContextRow.id,
                    ContextRow.keywords,
                    ContextRow.time,
                    ContextRow.trigger_count,
                    ContextRow.clear_time,
                ).where(ContextRow.keywords_hash == khash)
            )
            t_context_ms = (time.monotonic() - t0) * 1000.0
            ctx_row = result.one_or_none()
            if ctx_row is None:
                self._log_reply_query_slow(
                    keywords=keywords,
                    elapsed_ms=(time.monotonic() - t_start) * 1000.0,
                    context_ms=t_context_ms,
                    ban_ms=t_ban_ms,
                    answer_ms=t_answer_ms,
                    message_ms=t_message_ms,
                    ban_count=ban_count,
                    answer_count=answer_count,
                    message_count=message_count,
                    hit=False,
                )
                return None
            ctx_id, ctx_keywords, ctx_time, ctx_trigger_count, ctx_clear_time = ctx_row
            ctx_id = int(ctx_id)
            t0 = time.monotonic()
            ban_rows = list(
                (
                    await session.execute(
                        select(ContextBanRow).where(ContextBanRow.context_id == ctx_id).order_by(ContextBanRow.id)
                    )
                )
                .scalars()
                .all()
            )
            t_ban_ms = (time.monotonic() - t0) * 1000.0
            ban_count = len(ban_rows)
            t0 = time.monotonic()
            ans_result = await session.execute(
                select(ContextAnswerRow)
                .where(ContextAnswerRow.context_id == ctx_id)
                .order_by(ContextAnswerRow.count.desc(), ContextAnswerRow.time.desc())
                .limit(ans_cap)
            )
            answer_rows = list(ans_result.scalars().all())
            t_answer_ms = (time.monotonic() - t0) * 1000.0
            answer_count = len(answer_rows)
            if not answer_rows:
                self._log_reply_query_slow(
                    keywords=keywords,
                    elapsed_ms=(time.monotonic() - t_start) * 1000.0,
                    context_ms=t_context_ms,
                    ban_ms=t_ban_ms,
                    answer_ms=t_answer_ms,
                    message_ms=t_message_ms,
                    ban_count=ban_count,
                    answer_count=answer_count,
                    message_count=message_count,
                    hit=True,
                )
                return build_reply_context(
                    keywords=ctx_keywords,
                    time_value=ctx_time,
                    trigger_count=ctx_trigger_count,
                    clear_time=ctx_clear_time,
                    answer_rows=[],
                    ban_rows=ban_rows,
                    reply_messages={},
                )
            answer_ids = [int(answer.id) for answer in answer_rows]
            t0 = time.monotonic()
            msg_rows = (await session.execute(build_reply_message_query(answer_ids, msg_cap))).all()
            t_message_ms = (time.monotonic() - t0) * 1000.0
            message_count = len(msg_rows)
            reply_messages: dict[int, list[str]] = {}
            for aid, message, _mid in msg_rows:
                reply_messages.setdefault(int(aid), []).append(message)
            self._log_reply_query_slow(
                keywords=keywords,
                elapsed_ms=(time.monotonic() - t_start) * 1000.0,
                context_ms=t_context_ms,
                ban_ms=t_ban_ms,
                answer_ms=t_answer_ms,
                message_ms=t_message_ms,
                ban_count=ban_count,
                answer_count=answer_count,
                message_count=message_count,
                hit=True,
            )
            return build_reply_context(
                keywords=ctx_keywords,
                time_value=ctx_time,
                trigger_count=ctx_trigger_count,
                clear_time=ctx_clear_time,
                answer_rows=answer_rows,
                ban_rows=ban_rows,
                reply_messages=reply_messages,
            )

    @staticmethod
    def _log_reply_query_slow(
        *,
        keywords: str,
        elapsed_ms: float,
        context_ms: float,
        ban_ms: float,
        answer_ms: float,
        message_ms: float,
        ban_count: int,
        answer_count: int,
        message_count: int,
        hit: bool,
    ) -> None:
        threshold_ms = slow_path_threshold_ms("PALLAS_SLOW_REPLY_QUERY_MS", 250.0)
        if elapsed_ms < threshold_ms:
            return
        logger.debug(
            "corpus.reply_query slow_path elapsed_ms={:.1f} "
            "stages=context={:.1f}ms ban={:.1f}ms answers={:.1f}ms messages={:.1f}ms "
            "counts=ban:{} answers:{} messages:{} hit={} kw_len={}",
            elapsed_ms,
            context_ms,
            ban_ms,
            answer_ms,
            message_ms,
            ban_count,
            answer_count,
            message_count,
            hit,
            len(keywords),
        )

    async def save(self, context: Context) -> None:
        khash = keywords_hash(context.keywords)
        async with get_session() as session:
            result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            row = result.scalar_one_or_none()

            if row is None:
                row = ContextRow(
                    keywords=_s(context.keywords) or "",
                    keywords_hash=khash,
                    time=context.time,
                    trigger_count=context.trigger_count,
                    clear_time=context.clear_time,
                )
                session.add(row)
                await session.flush()
            else:
                row.time = context.time
                row.trigger_count = context.trigger_count
                row.clear_time = context.clear_time
                await session.execute(delete(ContextAnswerRow).where(ContextAnswerRow.context_id == row.id))
                await session.execute(delete(ContextBanRow).where(ContextBanRow.context_id == row.id))

            await _insert_answers_batched(session, row.id, context.answers)
            await _insert_bans_batched(session, row.id, context.ban)
            await session.commit()
        await clear_reply_query_snapshot_cache(context.keywords)

    async def insert(self, context: Context) -> None:
        """插入新 Context。并发下同 keywords 第二个写入会被 unique 约束拒绝，等价为 no-op。"""
        khash = keywords_hash(context.keywords)
        try:
            async with get_session() as session:
                row = ContextRow(
                    keywords=_s(context.keywords) or "",
                    keywords_hash=khash,
                    time=context.time,
                    trigger_count=context.trigger_count,
                    clear_time=context.clear_time,
                )
                session.add(row)
                await session.flush()
                await _insert_answers_batched(session, row.id, context.answers)
                await _insert_bans_batched(session, row.id, context.ban)
                await session.commit()
            await clear_reply_query_snapshot_cache(context.keywords)
        except IntegrityError:
            pass

    _DELETE_EXPIRED_CHUNK = 10000

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        """分批删除过期 Context，避免千万级时长锁表。级联删除由 FK ondelete=CASCADE 处理。"""
        deleted_any = False
        while True:
            async with get_session() as session:
                subq = (
                    select(ContextRow.id)
                    .where(ContextRow.time < expiration, ContextRow.trigger_count < threshold)
                    .limit(self._DELETE_EXPIRED_CHUNK)
                    .subquery()
                )
                result = await session.execute(
                    delete(ContextRow).where(ContextRow.id.in_(select(subq.c.id))).returning(ContextRow.id)
                )
                deleted = len(result.scalars().all())
                await session.commit()
            deleted_any = deleted_any or deleted > 0
            if deleted < self._DELETE_EXPIRED_CHUNK:
                break
        if deleted_any:
            await clear_reply_query_snapshot_cache(None)

    _CLEANUP_CHUNK = 500

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        """
        语义对齐 Mongo：trigger_count > threshold OR clear_time < expiration。
        流式按主键 id 分页，避免千万级时一次性全加载 OOM。
        """
        results: list[Context] = []
        last_id = 0
        while True:
            async with get_session(read_only=True) as session:
                result = await session.execute(
                    select(ContextRow)
                    .options(*_LOAD_RELATED)
                    .where(
                        or_(
                            ContextRow.trigger_count > trigger_threshold,
                            ContextRow.clear_time < expiration,
                        ),
                        ContextRow.id > last_id,
                    )
                    .order_by(ContextRow.id)
                    .limit(self._CLEANUP_CHUNK)
                )
                rows = list(result.scalars().all())
            if not rows:
                break
            results.extend(row_to_context(r) for r in rows)
            last_id = rows[-1].id
            if len(rows) < self._CLEANUP_CHUNK:
                break
        return results

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        """
        原子 upsert，依赖 UNIQUE(context_id, group_id, keywords)：
          - INSERT ... ON CONFLICT DO UPDATE SET count = count + 1, time = EXCLUDED.time
          - RETURNING 中借助 xmax 判断 insert vs update，决定是否 append message
          - 最后原子递增 Context.trigger_count / 更新 time
        """
        khash = keywords_hash(keywords)
        ans_kw_s = _s(answer_keywords) or ""
        msg_s = _s(message) or ""
        if reject_corpus_learn_message(msg_s, source="upsert_answer"):
            return

        async with get_session() as session:
            ctx_result = await session.execute(select(ContextRow.id).where(ContextRow.keywords_hash == khash))
            ctx_id = ctx_result.scalar_one_or_none()
            if ctx_id is None:
                return

            stmt = pg_insert(ContextAnswerRow).values(
                context_id=ctx_id,
                keywords=ans_kw_s,
                keywords_hash=keywords_hash(ans_kw_s),
                group_id=group_id,
                count=1,
                time=answer_time,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_context_answer_ctx_group_kw",
                set_={
                    "count": ContextAnswerRow.count + 1,
                    "time": stmt.excluded.time,
                },
            ).returning(ContextAnswerRow.id, literal_column("(xmax = 0)").label("was_insert"))

            row = (await session.execute(stmt)).first()
            assert row is not None
            ans_id, was_insert = int(row.id), bool(row.was_insert)

            if was_insert or append_on_existing:
                await session.execute(insert(ContextAnswerMessageRow).values(answer_id=ans_id, message=msg_s))

            await session.execute(
                update(ContextRow)
                .where(ContextRow.id == ctx_id)
                .values(trigger_count=ContextRow.trigger_count + 1, time=answer_time)
            )
            await session.commit()

    async def learn_answer(
        self,
        *,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> bool:
        """
        学习热路径专用：
          - Context 不存在时直接原子创建并写入首条 Answer
          - Context 已存在时在同一事务内原子 upsert Answer
        返回值表示本次是否新建了 Context。
        """
        khash = keywords_hash(keywords)
        kw_s = _s(keywords) or ""
        ans_kw_s = _s(answer_keywords) or ""
        msg_s = _s(message) or ""
        if reject_corpus_learn_message(msg_s, source="learn_answer"):
            return False

        async with get_session() as session:
            ctx_stmt = pg_insert(ContextRow).values(
                keywords=kw_s,
                keywords_hash=khash,
                time=answer_time,
                trigger_count=1,
                clear_time=0,
            )
            ctx_stmt = ctx_stmt.on_conflict_do_update(
                index_elements=[ContextRow.keywords_hash],
                set_={
                    "trigger_count": ContextRow.trigger_count + 1,
                    "time": ctx_stmt.excluded.time,
                },
            ).returning(ContextRow.id, literal_column("(xmax = 0)").label("was_insert"))

            ctx_row = (await session.execute(ctx_stmt)).first()
            assert ctx_row is not None
            ctx_id, ctx_created = int(ctx_row.id), bool(ctx_row.was_insert)

            ans_stmt = pg_insert(ContextAnswerRow).values(
                context_id=ctx_id,
                keywords=ans_kw_s,
                keywords_hash=keywords_hash(ans_kw_s),
                group_id=group_id,
                count=1,
                time=answer_time,
            )
            ans_stmt = ans_stmt.on_conflict_do_update(
                constraint="uq_context_answer_ctx_group_kw",
                set_={
                    "count": ContextAnswerRow.count + 1,
                    "time": ans_stmt.excluded.time,
                },
            ).returning(ContextAnswerRow.id, literal_column("(xmax = 0)").label("was_insert"))

            ans_row = (await session.execute(ans_stmt)).first()
            assert ans_row is not None
            ans_id, answer_created = int(ans_row.id), bool(ans_row.was_insert)

            if answer_created or append_on_existing:
                await session.execute(insert(ContextAnswerMessageRow).values(answer_id=ans_id, message=msg_s))

            await session.commit()
            if ctx_created:
                await clear_reply_query_snapshot_cache(keywords)
            return ctx_created

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        khash = keywords_hash(keywords)
        async with get_session() as session:
            ctx_result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            ctx_row = ctx_result.scalar_one_or_none()
            if ctx_row is None:
                return

            ctx_id = int(ctx_row.id)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ctx_id})

            kept_ids: list[int] = []
            for answer in answers:
                kw = _s(answer.keywords) or ""
                ans_stmt = (
                    pg_insert(ContextAnswerRow)
                    .values(
                        context_id=ctx_id,
                        keywords=kw,
                        keywords_hash=keywords_hash(kw),
                        group_id=answer.group_id,
                        count=answer.count,
                        time=answer.time,
                    )
                    .on_conflict_do_update(
                        constraint="uq_context_answer_ctx_group_kw",
                        set_={
                            "keywords": kw,
                            "count": answer.count,
                            "time": answer.time,
                        },
                    )
                    .returning(ContextAnswerRow.id)
                )
                ans_id = int((await session.execute(ans_stmt)).scalar_one())
                kept_ids.append(ans_id)

                await session.execute(
                    delete(ContextAnswerMessageRow).where(ContextAnswerMessageRow.answer_id == ans_id)
                )
                msg_rows = [
                    ContextAnswerMessageRow(answer_id=ans_id, message=_s(message) or "") for message in answer.messages
                ]
                for offset in range(0, len(msg_rows), _MSG_BATCH):
                    session.add_all(msg_rows[offset : offset + _MSG_BATCH])
                    await session.flush()

            await delete_context_answer_orphans(session, ctx_id=ctx_id, kept_ids=kept_ids)

            ctx_row.clear_time = clear_time
            await session.commit()
        await clear_reply_query_snapshot_cache(keywords)

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        khash = keywords_hash(keywords)
        async with get_session() as session:
            ctx_result = await session.execute(select(ContextRow.id).where(ContextRow.keywords_hash == khash))
            ctx_id = ctx_result.scalar_one_or_none()
            if ctx_id is None:
                return

            await session.execute(
                insert(ContextBanRow).values(
                    context_id=ctx_id,
                    keywords=_s(ban.keywords) or "",
                    group_id=ban.group_id,
                    reason=_s(ban.reason) or "",
                    time=ban.time,
                )
            )
            await session.commit()
        await clear_reply_query_snapshot_cache(keywords)

    async def find_ban_reply_target(self, group_id: int, reply_message: str) -> tuple[str, str] | None:
        async with get_session(read_only=True) as session:
            result = await session.execute(
                select(ContextRow.keywords, ContextAnswerRow.keywords)
                .join(ContextAnswerRow, ContextAnswerRow.context_id == ContextRow.id)
                .join(ContextAnswerMessageRow, ContextAnswerMessageRow.answer_id == ContextAnswerRow.id)
                .where(
                    ContextAnswerRow.group_id == int(group_id),
                    ContextAnswerMessageRow.message == _s(reply_message),
                )
                .order_by(ContextAnswerRow.time.desc(), ContextAnswerMessageRow.id.desc())
                .limit(1)
            )
            row = result.one_or_none()
            if row is None:
                return None
            pre_keywords, reply_keywords = row
            return str(pre_keywords), str(reply_keywords)

    async def list_answers_for_group_since(self, group_id: int, cutoff_time: int) -> list[Answer]:
        from pallas.core.foundation.db.modules import Answer

        async with get_session(read_only=True) as session:
            result = await session.execute(
                select(ContextAnswerRow)
                .where(
                    ContextAnswerRow.group_id == int(group_id),
                    ContextAnswerRow.time >= int(cutoff_time),
                )
                .options(selectinload(ContextAnswerRow.messages))
            )
            rows = list(result.scalars().all())
        return [
            Answer(
                keywords=str(row.keywords),
                group_id=int(row.group_id),
                count=int(row.count),
                time=int(row.time),
                messages=[str(msg.message) for msg in row.messages],
            )
            for row in rows
        ]


def row_to_message(row: MessageRow) -> Message:
    from pallas.core.foundation.db.modules import Message

    return Message.model_construct(
        group_id=int(row.group_id),
        user_id=int(row.user_id),
        bot_id=int(row.bot_id),
        raw_message=str(row.raw_message),
        is_plain_text=bool(row.is_plain_text),
        plain_text=str(row.plain_text),
        keywords=str(row.keywords),
        time=int(row.time),
    )


class PgMessageRepository:
    # MessageRow 有 8 列，asyncpg 单语句参数上限 32767，保守取 4000 行/批
    _BULK_BATCH_SIZE = 4000

    async def find_recent_in_group(
        self,
        group_id: int,
        *,
        before_time: int | None = None,
        user_id: int | None = None,
        limit: int = 8,
    ) -> list[Message]:
        cap = max(1, min(int(limit), 32))
        stmt = select(MessageRow).where(MessageRow.group_id == int(group_id))
        if before_time is not None:
            stmt = stmt.where(MessageRow.time < int(before_time))
        if user_id is not None:
            stmt = stmt.where(MessageRow.user_id == int(user_id))
        stmt = stmt.order_by(MessageRow.time.desc()).limit(cap)
        async with get_session(read_only=True) as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        rows.reverse()
        return [row_to_message(r) for r in rows]

    async def list_recent_group_ids_for_bot(
        self,
        bot_id: int,
        *,
        since_time: int,
        limit: int = 128,
    ) -> list[int]:
        cap = max(1, min(int(limit), 512))
        stmt = (
            select(MessageRow.group_id)
            .where(MessageRow.bot_id == int(bot_id))
            .where(MessageRow.time >= int(since_time))
            .distinct()
            .order_by(MessageRow.group_id)
            .limit(cap)
        )
        async with get_session(read_only=True) as session:
            result = await session.execute(stmt)
            return [int(row[0]) for row in result.all()]

    async def list_recent_bot_ids_for_group(
        self,
        group_id: int,
        *,
        since_time: int,
        limit: int = 32,
    ) -> list[int]:
        cap = max(1, min(int(limit), 128))
        stmt = (
            select(MessageRow.bot_id)
            .where(MessageRow.group_id == int(group_id))
            .where(MessageRow.time >= int(since_time))
            .distinct()
            .order_by(MessageRow.bot_id)
            .limit(cap)
        )
        async with get_session(read_only=True) as session:
            result = await session.execute(stmt)
            return [int(row[0]) for row in result.all()]

    async def bulk_insert(self, messages: list[Message]) -> None:
        if not messages:
            return
        async with get_session() as session:
            for i in range(0, len(messages), self._BULK_BATCH_SIZE):
                batch = messages[i : i + self._BULK_BATCH_SIZE]
                values = [
                    {
                        "group_id": m.group_id,
                        "user_id": m.user_id,
                        "bot_id": m.bot_id,
                        "raw_message": _s(m.raw_message) or "",
                        "is_plain_text": m.is_plain_text,
                        "plain_text": _s(m.plain_text) or "",
                        "keywords": _s(m.keywords) or "",
                        "time": m.time,
                    }
                    for m in batch
                ]
                # 走 Core executemany，避免 ORM 构造开销
                await session.execute(insert(MessageRow), values)
            await session.commit()


class PgBlackListRepository:
    async def find_all(self):
        async with get_session() as session:
            result = await session.execute(select(BlackListRow))
            rows = result.scalars().all()
            return [row_to_blacklist(r) for r in rows]

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        """原子 upsert，基于 group_id 唯一约束。"""
        cleaned = _strip_null_deep(answers)
        async with get_session() as session:
            stmt = pg_insert(BlackListRow).values(group_id=group_id, answers=cleaned, answers_reserve=[])
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id"],
                set_={"answers": stmt.excluded.answers},
            )
            await session.execute(stmt)
            await session.commit()

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        cleaned = _strip_null_deep(answers)
        async with get_session() as session:
            stmt = pg_insert(BlackListRow).values(group_id=group_id, answers=[], answers_reserve=cleaned)
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id"],
                set_={"answers_reserve": stmt.excluded.answers_reserve},
            )
            await session.execute(stmt)
            await session.commit()


_CONFIG_TABLE_MAP: dict[str, tuple[type, str]] = {
    "bot_config": (BotConfigRow, "account"),
    "group_config": (GroupConfigRow, "group_id"),
    "user_config": (UserConfigRow, "user_id"),
}


def row_to_admin_member(row: AdminMemberRow):
    from pallas.core.foundation.db.modules import AdminMember

    return AdminMember.model_construct(
        id=row.id,
        scope=row.scope,
        bot_id=row.bot_id,
        user_id=row.user_id,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def row_to_pallas_acl(row: PallasACLRow):
    from pallas.core.foundation.db.modules import PallasACL

    return PallasACL.model_construct(
        id=row.id,
        role=row.role,
        subject=row.subject,
        action=row.action,
        target_scope=row.target_scope,
        target=row.target,
        effect=row.effect,
        priority=row.priority,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgAdminRepository:
    """PG 版 AdminRepository。"""

    async def is_admin(self, user_id: int, *, bot_id: int | None = None) -> bool:
        async with get_session(read_only=True) as session:
            stmt = select(AdminMemberRow.id).where(AdminMemberRow.user_id == int(user_id))
            if bot_id is not None:
                stmt = stmt.where(
                    or_(
                        AdminMemberRow.scope == "bot",
                        AdminMemberRow.scope == "all",
                    )
                ).where(
                    or_(
                        AdminMemberRow.scope == "all",
                        AdminMemberRow.bot_id == int(bot_id),
                    )
                )
            else:
                stmt = stmt.where(AdminMemberRow.scope == "all")
            row = (await session.execute(stmt.limit(1))).scalar_one_or_none()
            return row is not None

    async def upsert_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
        note: str | None = None,
    ) -> Any:
        now = int(time.time())
        scope_norm = "bot" if scope not in ("bot", "all") else scope
        bot_id_norm = int(bot_id) if scope_norm == "bot" and bot_id is not None else None
        async with get_session() as session:
            stmt = pg_insert(AdminMemberRow).values(
                scope=scope_norm,
                bot_id=bot_id_norm,
                user_id=int(user_id),
                note=note,
                created_at=now,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["scope", "bot_id", "user_id"],
                set_={
                    "updated_at": stmt.excluded.updated_at,
                    "note": stmt.excluded.note,
                },
            )
            row = (await session.execute(stmt.returning(AdminMemberRow))).scalar_one()
            await session.commit()
            return row_to_admin_member(row)

    async def remove_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
    ) -> int:
        scope_norm = "bot" if scope not in ("bot", "all") else scope
        bot_id_norm = int(bot_id) if scope_norm == "bot" and bot_id is not None else None
        async with get_session() as session:
            result = await session.execute(
                delete(AdminMemberRow).where(
                    AdminMemberRow.scope == scope_norm,
                    AdminMemberRow.bot_id == bot_id_norm,
                    AdminMemberRow.user_id == int(user_id),
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_member(self, member_id: Any) -> int:
        async with get_session() as session:
            result = await session.execute(delete(AdminMemberRow).where(AdminMemberRow.id == int(member_id)))
            await session.commit()
            return int(result.rowcount or 0)

    async def list_members(
        self,
        *,
        scope: str | None = None,
        bot_id: int | None = None,
    ) -> list[Any]:
        async with get_session(read_only=True) as session:
            stmt = select(AdminMemberRow)
            if scope is not None:
                stmt = stmt.where(AdminMemberRow.scope == scope)
            if bot_id is not None:
                stmt = stmt.where(AdminMemberRow.bot_id == int(bot_id))
            rows = (await session.execute(stmt)).scalars().all()
            return [row_to_admin_member(r) for r in rows]


class PgAclRepository:
    """PG 版 AclRepository。"""

    async def list_rules(
        self,
        *,
        action: str | None = None,
        target: str | None = None,
        role: str | None = None,
        subject: str | None = None,
    ) -> list[Any]:
        async with get_session(read_only=True) as session:
            stmt = select(PallasACLRow)
            if action is not None:
                stmt = stmt.where(PallasACLRow.action == action)
            if target is not None:
                stmt = stmt.where(PallasACLRow.target == target)
            if role is not None:
                stmt = stmt.where(PallasACLRow.role == role)
            if subject is not None:
                stmt = stmt.where(PallasACLRow.subject == subject)
            rows = (await session.execute(stmt)).scalars().all()
            return [row_to_pallas_acl(r) for r in rows]

    async def list_all(self) -> list[Any]:
        async with get_session(read_only=True) as session:
            rows = (await session.execute(select(PallasACLRow))).scalars().all()
            return [row_to_pallas_acl(r) for r in rows]

    async def list_matching_rules(
        self,
        *,
        action: str,
        target: str | None = None,
    ) -> list[Any]:
        async with get_session(read_only=True) as session:
            stmt = select(PallasACLRow).where(PallasACLRow.action == action)
            if target is not None:
                stmt = stmt.where(
                    or_(
                        PallasACLRow.target == "*",
                        PallasACLRow.target == target,
                    )
                )
            rows = (await session.execute(stmt)).scalars().all()
            return [row_to_pallas_acl(r) for r in rows]

    async def upsert_rule(
        self,
        *,
        role: str,
        subject: str | None,
        action: str,
        target_scope: str,
        target: str,
        effect: str,
        priority: int,
        source: str,
    ) -> Any:
        now = int(time.time())
        async with get_session() as session:
            stmt = pg_insert(PallasACLRow).values(
                role=role,
                subject=subject,
                action=action,
                target_scope=target_scope,
                target=target,
                effect=effect,
                priority=int(priority),
                source=source,
                created_at=now,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "role",
                    "subject",
                    "action",
                    "target_scope",
                    "target",
                ],
                set_={
                    "effect": stmt.excluded.effect,
                    "priority": stmt.excluded.priority,
                    "source": stmt.excluded.source,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            row = (await session.execute(stmt.returning(PallasACLRow))).scalar_one()
            await session.commit()
            return row_to_pallas_acl(row)

    async def delete_rule(self, rule_id: Any) -> int:
        try:
            rid = int(rule_id)
        except (TypeError, ValueError):
            return 0
        async with get_session() as session:
            result = await session.execute(
                delete(PallasACLRow).where(PallasACLRow.id == rid)
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_signature(
        self,
        *,
        role: str,
        subject: str | None,
        action: str,
        target_scope: str,
        target: str,
    ) -> int:
        async with get_session() as session:
            result = await session.execute(
                delete(PallasACLRow).where(
                    PallasACLRow.role == role,
                    PallasACLRow.subject == subject,
                    PallasACLRow.action == action,
                    PallasACLRow.target_scope == target_scope,
                    PallasACLRow.target == target,
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def list_group_block_targets(self) -> set[str]:
        async with get_session(read_only=True) as session:
            stmt = select(PallasACLRow.target).where(
                PallasACLRow.target.like("group:%")
            )
            rows = (await session.execute(stmt)).scalars().all()
            return {row for row in rows if row}

    async def has_run_step(self, step: str) -> bool:
        async with get_session(read_only=True) as session:
            row = (
                await session.execute(
                    select(SchemaMigrationRow.id).where(SchemaMigrationRow.step == step).limit(1)
                )
            ).scalar_one_or_none()
            return row is not None

    async def mark_run_step(self, step: str) -> None:
        now = int(time.time())
        async with get_session() as session:
            stmt = pg_insert(SchemaMigrationRow).values(step=step, applied_at=now)
            stmt = stmt.on_conflict_do_update(
                index_elements=["step"],
                set_={"applied_at": stmt.excluded.applied_at},
            )
            await session.execute(stmt)
            await session.commit()


# ---------------------------------------------------------------------------
# 配置 Repository 的 TTL 缓存
# ---------------------------------------------------------------------------


def _cfg_env(key: str, default: str) -> str:
    try:
        import nonebot

        val = getattr(nonebot.get_driver().config, key.lower(), None)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, default)


class _ConfigCache:
    """
    简单的容量 + TTL 缓存，对齐 Mongo Beanie 的 model-level cache 语义。
    对每个 (row_class) 一个实例；key 是主键值，value 是 (row, expire_ts)
    None 也会被缓存。
    """

    def __init__(self, ttl: float, capacity: int) -> None:
        self._ttl = ttl
        self._capacity = capacity
        self._store: OrderedDict[Any, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: Any) -> tuple[bool, Any]:
        """TTL 缓存查询，返回 hit 与 value。"""
        if self._ttl <= 0 or self._capacity <= 0:
            return False, None
        async with self._lock:
            item = self._store.get(key)
            if item is None:
                return False, None
            value, expire_ts = item
            if expire_ts <= time.time():
                self._store.pop(key, None)
                return False, None
            self._store.move_to_end(key)
            return True, value

    async def put(self, key: Any, value: Any) -> None:
        if self._ttl <= 0 or self._capacity <= 0:
            return
        async with self._lock:
            self._store[key] = (value, time.time() + self._ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._capacity:
                self._store.popitem(last=False)

    async def invalidate(self, key: Any) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


_CONFIG_CACHES: dict[type, _ConfigCache] = {}


def _get_config_cache(row_class: type) -> _ConfigCache:
    cache = _CONFIG_CACHES.get(row_class)
    if cache is None:
        ttl = float(_cfg_env("PG_CONFIG_CACHE_TTL", "60"))
        capacity = int(_cfg_env("PG_CONFIG_CACHE_SIZE", "10000"))
        cache = _ConfigCache(ttl=ttl, capacity=capacity)
        _CONFIG_CACHES[row_class] = cache
    return cache


class PgConfigRepository:
    def __init__(self, table: str, primary_key: str) -> None:
        if table not in _CONFIG_TABLE_MAP:
            raise ValueError(f"Unknown config table: {table}")
        row_class, pk_field = _CONFIG_TABLE_MAP[table]
        # primary_key 由工厂函数传入，
        # 这里做一致性断言，避免静默与 _CONFIG_TABLE_MAP 失同步。
        if primary_key != pk_field:
            raise ValueError(f"primary_key {primary_key!r} 与 {table} 登记的主键 {pk_field!r} 不一致")
        self._row_class, self._pk_field = row_class, pk_field
        self._cache = _get_config_cache(self._row_class)

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        if not ignore_cache:
            hit, value = await self._cache.get(key_id)
            if hit:
                return value
        async with get_session(read_only=True) as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                session.expunge(row)
        await self._cache.put(key_id, row)
        return row

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        async with get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                session.expunge(row)
                await self._cache.put(key_id, row)
                return row, False
            try:
                new_row = self._row_class(**{self._pk_field: key_id, **_strip_null_deep(defaults)})
                session.add(new_row)
                await session.commit()
            except IntegrityError:
                # 并发下已被其他 writer 插入，回源拿最新行
                await session.rollback()
                result = await session.execute(
                    select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    session.expunge(existing)
                await self._cache.put(key_id, existing)
                return existing, False
            session.expunge(new_row)
            await self._cache.put(key_id, new_row)
            return new_row, True

    async def upsert_field(self, key_id: int, field: str, value: Any) -> None:
        """字段级 upsert，基于主键 ON CONFLICT 原子化。"""
        cleaned_value = _strip_null_deep(value)
        async with get_session() as session:
            stmt = pg_insert(self._row_class).values(**{self._pk_field: key_id, field: cleaned_value})
            stmt = stmt.on_conflict_do_update(
                index_elements=[self._pk_field],
                set_={field: getattr(stmt.excluded, field)},
            )
            await session.execute(stmt)
            await session.commit()
        await self._cache.invalidate(key_id)

    async def upsert_fields(self, key_id: int, fields: dict[str, Any]) -> None:
        """批量字段级 upsert"""
        if not fields:
            return
        cleaned = {k: _strip_null_deep(v) for k, v in fields.items()}
        async with get_session() as session:
            stmt = pg_insert(self._row_class).values(**{self._pk_field: key_id, **cleaned})
            stmt = stmt.on_conflict_do_update(
                index_elements=[self._pk_field],
                set_={k: getattr(stmt.excluded, k) for k in cleaned},
            )
            await session.execute(stmt)
            await session.commit()
        await self._cache.invalidate(key_id)

    async def invalidate_cache(self) -> None:
        await self._cache.clear()

    async def list_admin_user_ids(self, *, bot_id: int | None) -> list[int]:
        async with get_session(read_only=True) as session:
            stmt = select(AdminMemberRow.user_id).where(
                or_(
                    AdminMemberRow.scope == "all",
                    AdminMemberRow.scope == "bot",
                )
            )
            if bot_id is not None:
                stmt = stmt.where(
                    or_(
                        AdminMemberRow.scope == "all",
                        AdminMemberRow.bot_id == int(bot_id),
                    )
                )
            rows = (await session.execute(stmt)).scalars().all()
            return [int(r) for r in rows if r is not None]  # type: ignore[union-attr]  # noqa: E501


class PgImageCacheRepository:
    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        async with get_session(read_only=True) as session:
            result = await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == cq_code))
            row = result.scalar_one_or_none()
            return row_to_image_cache(row) if row else None

    async def insert(self, cache: ImageCache) -> None:
        """并发下相同 cq_code 的第二次 insert 等价为 no-op。

        blob_data 为 bytes，二进制字段不需要 NUL 剥离（_s() 也不适用）。
        """
        async with get_session() as session:
            stmt = pg_insert(ImageCacheRow).values(
                cq_code=_s(cache.cq_code) or "",
                blob_data=cache.blob_data,
                ref_times=cache.ref_times,
                date=cache.date,
            )
            await session.execute(stmt.on_conflict_do_nothing(index_elements=["cq_code"]))
            await session.commit()

    async def save(self, cache: ImageCache) -> None:
        """upsert 语义：存在则更新，否则插入。"""
        async with get_session() as session:
            stmt = pg_insert(ImageCacheRow).values(
                cq_code=_s(cache.cq_code) or "",
                blob_data=cache.blob_data,
                ref_times=cache.ref_times,
                date=cache.date,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["cq_code"],
                set_={
                    "ref_times": stmt.excluded.ref_times,
                    "date": stmt.excluded.date,
                    "blob_data": stmt.excluded.blob_data,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def delete_old(self, before_date: int) -> None:
        async with get_session() as session:
            await session.execute(delete(ImageCacheRow).where(ImageCacheRow.date < before_date))
            await session.commit()

    async def delete_low_ref(self, ref_threshold: int) -> None:
        async with get_session() as session:
            await session.execute(delete(ImageCacheRow).where(ImageCacheRow.ref_times < ref_threshold))
            await session.commit()
