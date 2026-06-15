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
    ForeignKey,
    Index,
    Integer,
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

from src.platform.observability import slow_path_threshold_ms

if TYPE_CHECKING:
    from src.foundation.db.modules import Answer, Ban, Context, ImageCache, Message

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


class GroupConfigRow(Base):
    __tablename__ = "group_config"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    roulette_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sing_progress: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)
    blocked_user_ids: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)


class UserConfigRow(Base):
    __tablename__ = "user_config"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    maa_devices: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=dict)
    maa_active_device: Mapped[str] = mapped_column(Text, nullable=False, default="")
    maa_stage_plan: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)


class ImageCacheRow(Base):
    __tablename__ = "image_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cq_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    base64_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_times: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    date: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)


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


def _ensure_pg_bot_config_community_roster_show_qq(connection) -> None:
    """旧库 bot_config 缺列时补列。"""
    insp = inspect(connection)
    if not insp.has_table("bot_config"):
        return
    names = {c["name"] for c in insp.get_columns("bot_config")}
    if "community_roster_show_qq" in names:
        return
    connection.execute(text("ALTER TABLE bot_config ADD COLUMN community_roster_show_qq BOOLEAN NOT NULL DEFAULT true"))


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


def _ensure_pg_message_group_time_index(connection) -> None:
    """旧库 message 补 (group_id, time) 复合索引，加速 find_recent_in_group。"""
    insp = inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_message_group_time ON message (group_id, time)"))


def _ensure_pg_message_group_user_time_index(connection) -> None:
    """旧库 message 补 (group_id, user_id, time) 复合索引，加速按用户回查最近消息。"""
    insp = inspect(connection)
    if not insp.has_table("message"):
        return
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_message_group_user_time ON message (group_id, user_id, time)")
    )


def _ensure_pg_context_answer_reply_index(connection) -> None:
    """旧库 context_answer 补 (context_id, count, time) 复合索引，加速接话热词 top-N answer。"""
    insp = inspect(connection)
    if not insp.has_table("context_answer"):
        return
    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_context_answer_ctx_count_time ON context_answer (context_id, count, time)")
    )


def _ensure_pg_context_answer_message_reply_index(connection) -> None:
    """旧库 context_answer_message 补 (answer_id, id) 复合索引，加速按 answer 取最近消息。"""
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
    from src.foundation.db.pool_budget import pg_pool_capacity

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
    from src.foundation.db.pool_diagnostics import (
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
        await conn.run_sync(_ensure_pg_bot_config_community_roster_show_qq)
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
    from src.foundation.db.modules import Answer, Ban, Context

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
    from src.foundation.db.modules import Answer, Ban, Context

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
    from src.features.corpus.find_cache import mark_reply_db_fail, reply_db_fail_active
    from src.features.corpus.reply_perf_config import reply_snapshot_max_entries, reply_snapshot_ttl_sec
    from src.foundation.db.pool_budget import is_pg_pool_timeout_error, pg_pool_under_pressure

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
    from src.foundation.db.modules import BlackList

    return BlackList.model_construct(
        group_id=row.group_id,
        answers=list(row.answers),
        answers_reserve=list(row.answers_reserve),
    )


def row_to_image_cache(row: ImageCacheRow) -> ImageCache:
    from src.foundation.db.modules import ImageCache

    return ImageCache.model_construct(
        cq_code=row.cq_code,
        base64_data=row.base64_data,
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
        from src.features.corpus.reply_perf_config import reply_query_caps

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


def row_to_message(row: MessageRow) -> Message:
    from src.foundation.db.modules import Message

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
        """返回 (hit, value)。miss 时 value 未定义。"""
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


class PgImageCacheRepository:
    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        async with get_session(read_only=True) as session:
            result = await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == cq_code))
            row = result.scalar_one_or_none()
            return row_to_image_cache(row) if row else None

    async def insert(self, cache: ImageCache) -> None:
        """并发下相同 cq_code 的第二次 insert 等价为 no-op。"""
        async with get_session() as session:
            stmt = pg_insert(ImageCacheRow).values(
                cq_code=_s(cache.cq_code) or "",
                base64_data=_s(cache.base64_data),
                ref_times=cache.ref_times,
                date=cache.date,
            )
            await session.execute(stmt.on_conflict_do_nothing(index_elements=["cq_code"]))
            await session.commit()

    async def save(self, cache: ImageCache) -> None:
        """与 Mongo save() 语义一致：存在则更新，不存在则插入。"""
        async with get_session() as session:
            stmt = pg_insert(ImageCacheRow).values(
                cq_code=_s(cache.cq_code) or "",
                base64_data=_s(cache.base64_data),
                ref_times=cache.ref_times,
                date=cache.date,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["cq_code"],
                set_={
                    "ref_times": stmt.excluded.ref_times,
                    "date": stmt.excluded.date,
                    "base64_data": stmt.excluded.base64_data,
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
