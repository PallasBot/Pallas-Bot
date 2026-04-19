"""PostgreSQL Repository 实现"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Text, delete, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

if TYPE_CHECKING:
    from src.common.db.modules import Answer, Ban, Context, ImageCache, Message

_JsonB = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class ContextAnswerRow(Base):
    __tablename__ = "context_answer"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    count: Mapped[int] = mapped_column(nullable=False, default=1)
    time: Mapped[int] = mapped_column(nullable=False, default=0)

    messages: Mapped[list[ContextAnswerMessageRow]] = relationship(
        "ContextAnswerMessageRow", cascade="all, delete-orphan", lazy="noload"
    )


class ContextAnswerMessageRow(Base):
    __tablename__ = "context_answer_message"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("context_answer.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ContextBanRow(Base):
    __tablename__ = "context_ban"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    context_id: Mapped[int] = mapped_column(ForeignKey("context.id", ondelete="CASCADE"), nullable=False, index=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[int] = mapped_column(nullable=False, default=0)


class ContextRow(Base):
    __tablename__ = "context"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    time: Mapped[int] = mapped_column(nullable=False, default=0)
    trigger_count: Mapped[int] = mapped_column(nullable=False, default=1)
    clear_time: Mapped[int] = mapped_column(nullable=False, default=0)

    answers: Mapped[list[ContextAnswerRow]] = relationship(
        "ContextAnswerRow", cascade="all, delete-orphan", lazy="noload"
    )
    ban: Mapped[list[ContextBanRow]] = relationship("ContextBanRow", cascade="all, delete-orphan", lazy="noload")


class MessageRow(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_message: Mapped[str] = mapped_column(Text, nullable=False)
    is_plain_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    time: Mapped[int] = mapped_column(nullable=False, default=0)


class BlackListRow(Base):
    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
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
    roulette_mode: Mapped[int] = mapped_column(nullable=False, default=1)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sing_progress: Mapped[Any] = mapped_column(_JsonB, nullable=True)
    disabled_plugins: Mapped[Any] = mapped_column(_JsonB, nullable=False, default=list)


class UserConfigRow(Base):
    __tablename__ = "user_config"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    banned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ImageCacheRow(Base):
    __tablename__ = "image_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cq_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    base64_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_times: Mapped[int] = mapped_column(nullable=False, default=1)
    date: Mapped[int] = mapped_column(nullable=False, index=True)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@asynccontextmanager
async def get_session():
    if _session_factory is None:
        raise RuntimeError("PostgreSQL 尚未初始化，请先调用 init_pg()")
    async with _session_factory() as session:
        yield session


async def init_pg(engine: AsyncEngine) -> None:
    """创建表结构并注入 engine"""
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
    import hashlib

    return hashlib.md5(keywords.encode()).hexdigest()


# asyncpg 单语句参数上限 32767
_ANSWER_BATCH = 500  # ContextAnswerRow 5 列 × 500 = 2500
_MSG_BATCH = 16000  # ContextAnswerMessageRow 2 列 × 16000 = 32000
_BAN_BATCH = 6000  # ContextBanRow 5 列 × 6000 = 30000


async def _insert_answers_batched(session: AsyncSession, context_id: int, answers) -> None:
    """分批插入 ContextAnswerRow 及其关联的 ContextAnswerMessageRow"""

    for i in range(0, len(answers), _ANSWER_BATCH):
        batch: list[Answer] = answers[i : i + _ANSWER_BATCH]
        # 先插入 answer 行（不带 messages 关系，避免 SQLAlchemy 一次性级联）
        rows = [
            ContextAnswerRow(
                context_id=context_id,
                keywords=a.keywords,
                group_id=a.group_id,
                count=a.count,
                time=a.time,
            )
            for a in batch
        ]
        session.add_all(rows)
        await session.flush()  # 获取自增 id

        # 再分批插入 message 行
        msg_rows = [
            ContextAnswerMessageRow(answer_id=rows[j].id, message=m) for j, a in enumerate(batch) for m in a.messages
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
                keywords=b.keywords,
                group_id=b.group_id,
                reason=b.reason,
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
                    keywords=context.keywords,
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
        khash = keywords_hash(context.keywords)
        try:
            async with get_session() as session:
                row = ContextRow(
                    keywords=context.keywords,
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
            # 另一个协程已插入相同 keywords，忽略即可
            pass

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        async with get_session() as session:
            await session.execute(
                delete(ContextRow).where(
                    ContextRow.time < expiration,
                    ContextRow.trigger_count < threshold,
                )
            )
            await session.commit()

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        async with get_session() as session:
            result = await session.execute(
                select(ContextRow)
                .options(*_LOAD_RELATED)
                .where(
                    ContextRow.trigger_count >= trigger_threshold,
                    ContextRow.clear_time <= expiration,
                )
            )
            rows = result.scalars().all()
            return [row_to_context(r) for r in rows]

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        khash = keywords_hash(keywords)
        async with get_session() as session:
            ctx_result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            ctx_row = ctx_result.scalar_one_or_none()
            if ctx_row is None:
                return

            ans_result = await session.execute(
                select(ContextAnswerRow).where(
                    ContextAnswerRow.context_id == ctx_row.id,
                    ContextAnswerRow.group_id == group_id,
                    ContextAnswerRow.keywords == answer_keywords,
                )
            )
            ans_row = ans_result.scalar_one_or_none()

            if ans_row is not None:
                ans_row.count += 1
                ans_row.time = answer_time
                if append_on_existing:
                    session.add(ContextAnswerMessageRow(answer_id=ans_row.id, message=message))
            else:
                new_ans = ContextAnswerRow(
                    context_id=ctx_row.id,
                    keywords=answer_keywords,
                    group_id=group_id,
                    count=1,
                    time=answer_time,
                )
                session.add(new_ans)
                await session.flush()
                session.add(ContextAnswerMessageRow(answer_id=new_ans.id, message=message))

            ctx_row.trigger_count += 1
            ctx_row.time = answer_time
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
            ctx_result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            ctx_row = ctx_result.scalar_one_or_none()
            if ctx_row is None:
                return

            session.add(
                ContextBanRow(
                    context_id=ctx_row.id,
                    keywords=ban.keywords,
                    group_id=ban.group_id,
                    reason=ban.reason,
                    time=ban.time,
                )
            )
            await session.commit()


class PgMessageRepository:
    # MessageRow 有 8 列，asyncpg 单语句参数上限 32767，保守取 4000 行/批
    _BULK_BATCH_SIZE = 4000

    async def bulk_insert(self, messages: list[Message]) -> None:
        async with get_session() as session:
            for i in range(0, len(messages), self._BULK_BATCH_SIZE):
                batch = messages[i : i + self._BULK_BATCH_SIZE]
                session.add_all([
                    MessageRow(
                        group_id=m.group_id,
                        user_id=m.user_id,
                        bot_id=m.bot_id,
                        raw_message=m.raw_message,
                        is_plain_text=m.is_plain_text,
                        plain_text=m.plain_text,
                        keywords=m.keywords,
                        time=m.time,
                    )
                    for m in batch
                ])
                await session.flush()
            await session.commit()


class PgBlackListRepository:
    async def find_all(self):
        async with get_session() as session:
            result = await session.execute(select(BlackListRow))
            rows = result.scalars().all()
            return [row_to_blacklist(r) for r in rows]

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        async with get_session() as session:
            result = await session.execute(select(BlackListRow).where(BlackListRow.group_id == group_id))
            row = result.scalar_one_or_none()
            if row is None:
                session.add(BlackListRow(group_id=group_id, answers=answers, answers_reserve=[]))
            else:
                row.answers = answers
            await session.commit()

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        async with get_session() as session:
            result = await session.execute(select(BlackListRow).where(BlackListRow.group_id == group_id))
            row = result.scalar_one_or_none()
            if row is None:
                session.add(BlackListRow(group_id=group_id, answers=[], answers_reserve=answers))
            else:
                row.answers_reserve = answers
            await session.commit()


_CONFIG_TABLE_MAP: dict[str, tuple[type, str]] = {
    "bot_config": (BotConfigRow, "account"),
    "group_config": (GroupConfigRow, "group_id"),
    "user_config": (UserConfigRow, "user_id"),
}


class PgConfigRepository:
    def __init__(self, table: str, primary_key: str) -> None:
        if table not in _CONFIG_TABLE_MAP:
            raise ValueError(f"Unknown config table: {table}")
        self._row_class, self._pk_field = _CONFIG_TABLE_MAP[table]

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        async with get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            return result.scalar_one_or_none()

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        async with get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                return row, False
            new_row = self._row_class(**{self._pk_field: key_id, **defaults})
            session.add(new_row)
            await session.commit()
            return new_row, True

    async def upsert_field(self, key_id: int, field: str, value: Any) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                await session.execute(
                    update(self._row_class)
                    .where(getattr(self._row_class, self._pk_field) == key_id)
                    .values(**{field: value})
                )
            else:
                session.add(self._row_class(**{self._pk_field: key_id, field: value}))
            await session.commit()

    async def invalidate_cache(self) -> None:
        return None


class PgImageCacheRepository:
    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        async with get_session() as session:
            result = await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == cq_code))
            row = result.scalar_one_or_none()
            return row_to_image_cache(row) if row else None

    async def insert(self, cache: ImageCache) -> None:
        try:
            async with get_session() as session:
                session.add(
                    ImageCacheRow(
                        cq_code=cache.cq_code,
                        base64_data=cache.base64_data,
                        ref_times=cache.ref_times,
                        date=cache.date,
                    )
                )
                await session.commit()
        except IntegrityError:
            # 另一个协程已插入相同 cq_code，忽略即可
            pass

    async def save(self, cache: ImageCache) -> None:
        async with get_session() as session:
            result = await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == cache.cq_code))
            row = result.scalar_one_or_none()
            if row is not None:
                row.ref_times = cache.ref_times
                row.date = cache.date
                row.base64_data = cache.base64_data
                await session.commit()

    async def delete_old(self, before_date: int) -> None:
        async with get_session() as session:
            await session.execute(delete(ImageCacheRow).where(ImageCacheRow.date < before_date))
            await session.commit()

    async def delete_low_ref(self, ref_threshold: int) -> None:
        async with get_session() as session:
            await session.execute(delete(ImageCacheRow).where(ImageCacheRow.ref_times < ref_threshold))
            await session.commit()
