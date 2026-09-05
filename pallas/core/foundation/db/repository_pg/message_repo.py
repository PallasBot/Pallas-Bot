"""PostgreSQL Message Repository"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.repository_pg.lifecycle import _s
from pallas.core.foundation.db.repository_pg.schema import MessageRow

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import Message


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
        sender_name=str(row.sender_name or ""),
        message_id=int(row.message_id) if row.message_id is not None else None,
        reply_to_message_id=int(row.reply_to_message_id) if row.reply_to_message_id is not None else None,
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
        before_message_id: int | None = None,
        user_id: int | None = None,
        limit: int = 8,
    ) -> list:
        cap = max(1, min(int(limit), 32))
        stmt = select(MessageRow).where(MessageRow.group_id == int(group_id))
        if before_time is not None:
            if before_message_id is not None:
                stmt = stmt.where(
                    or_(
                        MessageRow.time < int(before_time),
                        and_(MessageRow.time == int(before_time), MessageRow.message_id < int(before_message_id)),
                    )
                )
            else:
                stmt = stmt.where(MessageRow.time < int(before_time))
        if user_id is not None:
            stmt = stmt.where(MessageRow.user_id == int(user_id))
        stmt = stmt.order_by(MessageRow.time.desc(), MessageRow.message_id.desc()).limit(cap)
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        rows.reverse()
        return [row_to_message(r) for r in rows]

    async def list_group_messages_after(
        self,
        group_id: int,
        *,
        after_time: int,
        after_message_id: int | None = None,
        limit: int = 2000,
    ) -> list:
        cap = max(1, min(int(limit), 4096))
        stmt = select(MessageRow).where(MessageRow.group_id == int(group_id))
        if after_message_id is None:
            stmt = stmt.where(MessageRow.time > int(after_time))
        else:
            stmt = stmt.where(
                or_(
                    MessageRow.time > int(after_time),
                    and_(MessageRow.time == int(after_time), MessageRow.message_id > int(after_message_id)),
                )
            )
        stmt = stmt.order_by(MessageRow.time.asc(), MessageRow.message_id.asc()).limit(cap)
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        return [row_to_message(r) for r in rows]

    async def find_recent_distinct_in_group(
        self,
        group_id: int,
        *,
        before_time: int | None = None,
        before_message_id: int | None = None,
        since_time: int | None = None,
        user_id: int | None = None,
        limit: int = 128,
    ) -> list:
        cap = max(1, min(int(limit), 256))
        partition_key = case((MessageRow.message_id.is_(None), MessageRow.id), else_=MessageRow.message_id)
        ranked = select(
            MessageRow,
            func
            .row_number()
            .over(partition_by=partition_key, order_by=(MessageRow.time.desc(), MessageRow.id.desc()))
            .label("_message_rank"),
        ).where(MessageRow.group_id == int(group_id))
        if before_time is not None:
            if before_message_id is not None:
                ranked = ranked.where(
                    or_(
                        MessageRow.time < int(before_time),
                        and_(MessageRow.time == int(before_time), MessageRow.message_id < int(before_message_id)),
                    )
                )
            else:
                ranked = ranked.where(MessageRow.time < int(before_time))
        if since_time is not None:
            ranked = ranked.where(MessageRow.time >= int(since_time))
        if user_id is not None:
            ranked = ranked.where(MessageRow.user_id == int(user_id))
        ranked_subquery = ranked.subquery()
        ranked_message = aliased(MessageRow, ranked_subquery)
        stmt = (
            select(ranked_message)
            .where(ranked_subquery.c._message_rank == 1)
            .order_by(
                ranked_message.time.desc(),
                ranked_message.message_id.desc().nullslast(),
                ranked_message.id.desc(),
            )
            .limit(cap)
        )
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        rows.reverse()
        return [row_to_message(r) for r in rows]

    async def find_by_message_ids(self, group_id: int, message_ids: list[int]) -> list:
        # 注意 QQ 新版 message_id 可能是负数，isdigit() 不认负号会误过滤，导致引用图查不到。
        ids = {int(item) for item in message_ids if str(item or "").strip().lstrip("-").isdigit() and item is not None}
        if not ids:
            return []
        stmt = (
            select(MessageRow).where(MessageRow.group_id == int(group_id)).where(MessageRow.message_id.in_(list(ids)))
        )
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        return [row_to_message(r) for r in rows]

    async def list_recent_group_ids_for_bot(
        self,
        bot_id: int,
        *,
        since_time: int,
        limit: int = 128,
    ) -> list:
        cap = max(1, min(int(limit), 512))
        stmt = (
            select(MessageRow.group_id)
            .where(MessageRow.bot_id == int(bot_id))
            .where(MessageRow.time >= int(since_time))
            .distinct()
            .order_by(MessageRow.group_id)
            .limit(cap)
        )
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(stmt)
            return [int(row[0]) for row in result.all()]

    async def list_recent_bot_ids_for_group(
        self,
        group_id: int,
        *,
        since_time: int,
        limit: int = 32,
    ) -> list:
        cap = max(1, min(int(limit), 128))
        stmt = (
            select(MessageRow.bot_id)
            .where(MessageRow.group_id == int(group_id))
            .where(MessageRow.time >= int(since_time))
            .distinct()
            .order_by(MessageRow.bot_id)
            .limit(cap)
        )
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(stmt)
            return [int(row[0]) for row in result.all()]

    async def bulk_insert(self, messages: list) -> None:
        if not messages:
            return
        async with _repo.get_session() as session:
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
                        "sender_name": _s(m.sender_name) or "",
                        "message_id": m.message_id,
                        "reply_to_message_id": m.reply_to_message_id,
                        "suppressed_by_rage": bool(getattr(m, "suppressed_by_rage", False)),
                        "time": m.time,
                    }
                    for m in batch
                ]
                # 幂等落库：同 (group_id, bot_id, message_id) 已存在则跳过。
                # message_id 为 NULL 的行不参与冲突判定（PG 中 NULL <> NULL）。
                stmt = pg_insert(MessageRow).on_conflict_do_nothing(index_elements=["group_id", "bot_id", "message_id"])
                # 走 Core executemany，避免 ORM 构造开销
                await session.execute(stmt, values)
            await session.commit()
