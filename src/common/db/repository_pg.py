"""PostgreSQL Repository 实现"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

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
    insert,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

if TYPE_CHECKING:
    from src.common.db.modules import Answer, Ban, Context, ImageCache, Message

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
    __table_args__ = (
        UniqueConstraint("context_id", "group_id", "keywords", name="uq_context_answer_ctx_group_kw"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    messages: Mapped[list[ContextAnswerMessageRow]] = relationship(
        "ContextAnswerMessageRow", cascade="all, delete-orphan", lazy="noload"
    )


class ContextAnswerMessageRow(Base):
    __tablename__ = "context_answer_message"

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
    __table_args__ = (Index("ix_message_time", "time"),)

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


class GroupConfigRow(Base):
    __tablename__ = "group_config"

    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    roulette_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sing_progress: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)


class UserConfigRow(Base):
    __tablename__ = "user_config"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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


@asynccontextmanager
async def get_session():
    if _session_factory is None:
        raise RuntimeError("PostgreSQL 尚未初始化，请先调用 init_pg()")
    async with _session_factory() as session:
        yield session


async def init_pg(engine: AsyncEngine) -> None:
    """创建表结构并注入 engine。新库首次启动时会建出当前最新 schema。"""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_pg() -> None:
    """关闭连接池，bot 退出时调用"""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


_LOAD_RELATED = [
    selectinload(ContextRow.answers).selectinload(ContextAnswerRow.messages),
    selectinload(ContextRow.ban),
]


def keywords_hash(keywords: str) -> str:
    # 先剥除 \x00 再哈希，与 ContextRow.keywords 实际存储值保持一致
    clean = keywords.replace("\x00", "") if keywords and "\x00" in keywords else keywords
    return hashlib.md5((clean or "").encode("utf-8", errors="replace")).hexdigest()


# asyncpg 单语句参数上限 32767
_ANSWER_BATCH = 500  # ContextAnswerRow 5 列 × 500 = 2500
_MSG_BATCH = 16000  # ContextAnswerMessageRow 2 列 × 16000 = 32000
_BAN_BATCH = 6000  # ContextBanRow 5 列 × 6000 = 30000


async def _insert_answers_batched(session: AsyncSession, context_id: int, answers) -> None:
    """分批插入 ContextAnswerRow 及其关联的 ContextAnswerMessageRow"""

    for i in range(0, len(answers), _ANSWER_BATCH):
        batch: list[Answer] = answers[i : i + _ANSWER_BATCH]
        rows = [
            ContextAnswerRow(
                context_id=context_id,
                keywords=_s(a.keywords) or "",
                group_id=a.group_id,
                count=a.count,
                time=a.time,
            )
            for a in batch
        ]
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


def row_to_context(row: ContextRow) -> Context:
    from src.common.db.modules import Answer, Ban, Context

    answers = [
        Answer.model_construct(
            keywords=a.keywords,
            group_id=a.group_id,
            count=a.count,
            time=a.time,
            messages=[m.message for m in a.messages],
        )
        for a in row.answers
    ]
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


def row_to_blacklist(row: BlackListRow):
    from src.common.db.modules import BlackList

    return BlackList.model_construct(
        group_id=row.group_id,
        answers=list(row.answers),
        answers_reserve=list(row.answers_reserve),
    )


def row_to_image_cache(row: ImageCacheRow) -> ImageCache:
    from src.common.db.modules import ImageCache

    return ImageCache.model_construct(
        cq_code=row.cq_code,
        base64_data=row.base64_data,
        ref_times=row.ref_times,
        date=row.date,
    )


class PgContextRepository:
    async def find_by_keywords(self, keywords: str) -> Context | None:
        khash = keywords_hash(keywords)
        async with get_session() as session:
            result = await session.execute(
                select(ContextRow).options(*_LOAD_RELATED).where(ContextRow.keywords_hash == khash)
            )
            row = result.scalar_one_or_none()
            return row_to_context(row) if row else None

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
        except IntegrityError:
            pass

    _DELETE_EXPIRED_CHUNK = 10000

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        """分批删除过期 Context，避免千万级时长锁表。级联删除由 FK ondelete=CASCADE 处理。"""
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
            if deleted < self._DELETE_EXPIRED_CHUNK:
                break

    _CLEANUP_CHUNK = 500

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        """
        语义对齐 Mongo：trigger_count > threshold OR clear_time < expiration。
        流式按主键 id 分页，避免千万级时一次性全加载 OOM。
        """
        results: list[Context] = []
        last_id = 0
        while True:
            async with get_session() as session:
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
            ctx_result = await session.execute(
                select(ContextRow.id).where(ContextRow.keywords_hash == khash)
            )
            ctx_id = ctx_result.scalar_one_or_none()
            if ctx_id is None:
                return

            stmt = pg_insert(ContextAnswerRow).values(
                context_id=ctx_id,
                keywords=ans_kw_s,
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
                await session.execute(
                    insert(ContextAnswerMessageRow).values(answer_id=ans_id, message=msg_s)
                )

            await session.execute(
                update(ContextRow)
                .where(ContextRow.id == ctx_id)
                .values(trigger_count=ContextRow.trigger_count + 1, time=answer_time)
            )
            await session.commit()

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        khash = keywords_hash(keywords)
        async with get_session() as session:
            ctx_result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            ctx_row = ctx_result.scalar_one_or_none()
            if ctx_row is None:
                return

            await session.execute(delete(ContextAnswerRow).where(ContextAnswerRow.context_id == ctx_row.id))
            await _insert_answers_batched(session, ctx_row.id, answers)
            ctx_row.clear_time = clear_time
            await session.commit()

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


class PgMessageRepository:
    # MessageRow 有 8 列，asyncpg 单语句参数上限 32767，保守取 4000 行/批
    _BULK_BATCH_SIZE = 4000

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
    对每个 (row_class) 一个实例；key 是主键值，value 是 (row, expire_ts)；
    None 也会被缓存（避免缓存击穿）。
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
        self._row_class, self._pk_field = _CONFIG_TABLE_MAP[table]
        self._cache = _get_config_cache(self._row_class)

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        if not ignore_cache:
            hit, value = await self._cache.get(key_id)
            if hit:
                return value
        async with get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
        await self._cache.put(key_id, row)
        return row

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        async with get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
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
                await self._cache.put(key_id, existing)
                return existing, False
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

    async def invalidate_cache(self) -> None:
        await self._cache.clear()


class PgImageCacheRepository:
    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        async with get_session() as session:
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
