from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nonebot import logger
from sqlalchemy import delete, func, select

from pallas.core.foundation.db.repository_pg import LlmChatMessageRow, get_session
from pallas.core.foundation.logging import log_rate_limited
from pallas.product.llm.session_models import (
    ALLOWED_ROLES,
    LlmChatRole,
    LlmChatTurn,
    LlmHistorySessionSummary,
    LlmSessionSnapshotTurn,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _parse_pg_message_ids(raw_ids: Sequence[str]) -> list[int] | None:
    ids: list[int] = []
    for raw in raw_ids:
        text = str(raw)
        if not text or not text.isascii() or not text.isdigit():
            return None
        value = int(text)
        if value <= 0:
            return None
        ids.append(value)
    if not ids or len(set(ids)) != len(ids):
        return None
    return ids


class PgLlmSessionMessageBackend:
    async def append_message(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        role: LlmChatRole,
        content: str,
        *,
        ttl_sec: int,
        window: int,
    ) -> bool:
        now = int(time.time())
        async with get_session() as session:
            session.add(
                LlmChatMessageRow(
                    bot_id=int(bot_id),
                    group_id=int(group_id),
                    user_id=int(user_id),
                    role=role,
                    content=content,
                    created_at=now,
                )
            )
            await session.flush()
            await self._purge_user_ttl(
                session,
                bot_id=int(bot_id),
                group_id=int(group_id),
                user_id=int(user_id),
                ttl_sec=ttl_sec,
                now=now,
            )
            await self._trim_user_window(
                session,
                bot_id=int(bot_id),
                group_id=int(group_id),
                user_id=int(user_id),
                window=window,
            )
            if group_id != 0:
                await self._purge_group_ttl(
                    session,
                    bot_id=int(bot_id),
                    group_id=int(group_id),
                    ttl_sec=ttl_sec,
                    now=now,
                )
            await session.commit()
        return True

    async def list_user_messages(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        *,
        limit: int,
        ttl_sec: int,
    ) -> list[LlmChatTurn]:
        stmt = (
            select(LlmChatMessageRow)
            .where(
                LlmChatMessageRow.bot_id == int(bot_id),
                LlmChatMessageRow.group_id == int(group_id),
                LlmChatMessageRow.user_id == int(user_id),
            )
            .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
            .limit(limit)
        )
        if ttl_sec > 0:
            cutoff = int(time.time()) - ttl_sec
            stmt = stmt.where(LlmChatMessageRow.created_at >= cutoff)

        async with get_session(read_only=True) as session:
            rows = (await session.execute(stmt)).scalars().all()

        return [
            LlmChatTurn(
                role=row.role if row.role in ALLOWED_ROLES else "user",
                content=row.content,
                user_id=int(row.user_id),
                created_at=int(row.created_at),
            )
            for row in reversed(rows)
        ]

    async def read_user_compaction_snapshot(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        *,
        limit: int,
        ttl_sec: int,
    ) -> list[LlmSessionSnapshotTurn] | None:
        max_items = max(1, int(limit))
        stmt = (
            select(LlmChatMessageRow)
            .where(
                LlmChatMessageRow.bot_id == int(bot_id),
                LlmChatMessageRow.group_id == int(group_id),
                LlmChatMessageRow.user_id == int(user_id),
            )
            .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
            .limit(max_items + 1)
        )
        if ttl_sec > 0:
            cutoff = int(time.time()) - ttl_sec
            stmt = stmt.where(LlmChatMessageRow.created_at >= cutoff)

        async with get_session(read_only=True) as session:
            rows = (await session.execute(stmt)).scalars().all()
        if len(rows) > max_items:
            return None
        return [
            LlmSessionSnapshotTurn(
                role=row.role if row.role in ALLOWED_ROLES else "user",
                content=row.content,
                user_id=int(row.user_id),
                created_at=int(row.created_at),
                message_id=str(row.id),
            )
            for row in reversed(rows)
        ]

    async def list_group_ambient(
        self,
        bot_id: int,
        group_id: int,
        *,
        limit: int,
        ttl_sec: int,
    ) -> list[LlmChatTurn]:
        stmt = (
            select(LlmChatMessageRow)
            .where(
                LlmChatMessageRow.bot_id == int(bot_id),
                LlmChatMessageRow.group_id == int(group_id),
            )
            .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
            .limit(limit)
        )
        if ttl_sec > 0:
            cutoff = int(time.time()) - ttl_sec
            stmt = stmt.where(LlmChatMessageRow.created_at >= cutoff)

        async with get_session(read_only=True) as session:
            rows = (await session.execute(stmt)).scalars().all()

        return [
            LlmChatTurn(
                role=row.role if row.role in ALLOWED_ROLES else "user",
                content=row.content,
                user_id=int(row.user_id),
                created_at=int(row.created_at),
            )
            for row in reversed(rows)
        ]

    async def list_history_sessions(
        self,
        *,
        bot_id: int | None,
        group_id: int | None,
        user_id: int | None,
        limit: int,
    ) -> list[LlmHistorySessionSummary]:
        session_key = (LlmChatMessageRow.bot_id, LlmChatMessageRow.group_id, LlmChatMessageRow.user_id)
        session_rank = func.row_number().over(
            partition_by=session_key,
            order_by=(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc()),
        )
        ranked = select(
            LlmChatMessageRow.bot_id.label("bot_id"),
            LlmChatMessageRow.group_id.label("group_id"),
            LlmChatMessageRow.user_id.label("user_id"),
            LlmChatMessageRow.role.label("last_role"),
            LlmChatMessageRow.content.label("last_content"),
            LlmChatMessageRow.created_at.label("latest_created_at"),
            LlmChatMessageRow.id.label("latest_message_id"),
            func.count().over(partition_by=session_key).label("turn_count"),
            func.min(LlmChatMessageRow.created_at).over(partition_by=session_key).label("first_created_at"),
            func.max(LlmChatMessageRow.created_at).over(partition_by=session_key).label("last_created_at"),
            session_rank.label("session_rank"),
        )

        if bot_id is not None:
            ranked = ranked.where(LlmChatMessageRow.bot_id == int(bot_id))
        if group_id is not None:
            ranked = ranked.where(LlmChatMessageRow.group_id == int(group_id))
        if user_id is not None:
            ranked = ranked.where(LlmChatMessageRow.user_id == int(user_id))

        ranked_sessions = ranked.subquery()
        stmt = (
            select(ranked_sessions)
            .where(ranked_sessions.c.session_rank == 1)
            .order_by(ranked_sessions.c.latest_created_at.desc(), ranked_sessions.c.latest_message_id.desc())
            .limit(limit)
        )

        async with get_session(read_only=True) as session:
            rows = (await session.execute(stmt)).all()

        return [
            LlmHistorySessionSummary(
                session_key=f"{int(row.bot_id)}:{int(row.group_id)}:{int(row.user_id)}",
                bot_id=int(row.bot_id),
                group_id=int(row.group_id),
                user_id=int(row.user_id),
                turn_count=int(row.turn_count or 0),
                first_created_at=int(row.first_created_at or 0),
                last_created_at=int(row.last_created_at or 0),
                last_role=row.last_role if row.last_role in ALLOWED_ROLES else "user",
                last_content=str(row.last_content or ""),
            )
            for row in rows
        ]

    async def clear_group(self, bot_id: int, group_id: int) -> int:
        async with get_session() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(LlmChatMessageRow)
                    .where(
                        LlmChatMessageRow.bot_id == int(bot_id),
                        LlmChatMessageRow.group_id == int(group_id),
                    )
                )
            ).scalar_one()
            await session.execute(
                delete(LlmChatMessageRow).where(
                    LlmChatMessageRow.bot_id == int(bot_id),
                    LlmChatMessageRow.group_id == int(group_id),
                )
            )
            await session.commit()
        return int(count)

    async def clear_user(self, bot_id: int, group_id: int, user_id: int) -> int:
        async with get_session() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(LlmChatMessageRow)
                    .where(
                        LlmChatMessageRow.bot_id == int(bot_id),
                        LlmChatMessageRow.group_id == int(group_id),
                        LlmChatMessageRow.user_id == int(user_id),
                    )
                )
            ).scalar_one()
            await session.execute(
                delete(LlmChatMessageRow).where(
                    LlmChatMessageRow.bot_id == int(bot_id),
                    LlmChatMessageRow.group_id == int(group_id),
                    LlmChatMessageRow.user_id == int(user_id),
                )
            )
            await session.commit()
        return int(count)

    async def compact_user_with_summary(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        summary_content: str,
        *,
        keep_messages: int,
        source_message_ids: Sequence[str] | None = None,
        summary_created_at: int | None = None,
    ) -> bool:
        if source_message_ids is not None:
            if summary_created_at is None:
                return False
            message_ids = _parse_pg_message_ids(source_message_ids)
            if message_ids is None:
                return False
            return await self._compact_user_with_summary_ids(
                bot_id,
                group_id,
                user_id,
                summary_content,
                message_ids=message_ids,
                summary_created_at=int(summary_created_at),
            )
        keep = max(2, int(keep_messages))
        now = int(time.time())
        async with get_session() as session:
            rows = (
                (
                    await session.execute(
                        select(LlmChatMessageRow)
                        .where(
                            LlmChatMessageRow.bot_id == int(bot_id),
                            LlmChatMessageRow.group_id == int(group_id),
                            LlmChatMessageRow.user_id == int(user_id),
                        )
                        .order_by(LlmChatMessageRow.created_at.asc(), LlmChatMessageRow.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            if len(rows) <= keep:
                return False
            keep_rows = rows[-keep:]
            keep_ids = {row.id for row in keep_rows}
            stale_ids = [row.id for row in rows if row.id not in keep_ids]
            if stale_ids:
                await session.execute(delete(LlmChatMessageRow).where(LlmChatMessageRow.id.in_(stale_ids)))
            anchor_time = int(keep_rows[0].created_at) - 1 if keep_rows else now - 1
            session.add(
                LlmChatMessageRow(
                    bot_id=int(bot_id),
                    group_id=int(group_id),
                    user_id=int(user_id),
                    role="user",
                    content=summary_content,
                    created_at=anchor_time,
                )
            )
            await session.commit()
        return True

    async def _compact_user_with_summary_ids(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        summary_content: str,
        *,
        message_ids: list[int],
        summary_created_at: int,
    ) -> bool:
        async with get_session() as session:
            try:
                # 短事务：只按 scope + 来源 ID 删除，返回集合必须与预期全等。
                result = await session.execute(
                    delete(LlmChatMessageRow)
                    .where(
                        LlmChatMessageRow.bot_id == int(bot_id),
                        LlmChatMessageRow.group_id == int(group_id),
                        LlmChatMessageRow.user_id == int(user_id),
                        LlmChatMessageRow.id.in_(message_ids),
                    )
                    .returning(LlmChatMessageRow.id)
                )
                deleted_ids = {int(item) for item in result.scalars().all()}
                if deleted_ids != set(message_ids):
                    await session.rollback()
                    return False
                session.add(
                    LlmChatMessageRow(
                        bot_id=int(bot_id),
                        group_id=int(group_id),
                        user_id=int(user_id),
                        role="user",
                        content=summary_content,
                        created_at=int(summary_created_at),
                    )
                )
                await session.commit()
            except Exception as exc:
                log_rate_limited(
                    logger,
                    "warning",
                    "llm.session_store.pg_compaction_failed",
                    "PG session compaction failed for bot [{}], group [{}], user [{}]: [{}]",
                    int(bot_id),
                    int(group_id),
                    int(user_id),
                    type(exc).__name__,
                )
                await session.rollback()
                return False
        return True

    async def _purge_user_ttl(
        self,
        session,
        *,
        bot_id: int,
        group_id: int,
        user_id: int,
        ttl_sec: int,
        now: int,
    ) -> None:
        if ttl_sec <= 0:
            return
        cutoff = now - ttl_sec
        await session.execute(
            delete(LlmChatMessageRow).where(
                LlmChatMessageRow.bot_id == bot_id,
                LlmChatMessageRow.group_id == group_id,
                LlmChatMessageRow.user_id == user_id,
                LlmChatMessageRow.created_at < cutoff,
            )
        )

    async def _purge_group_ttl(
        self,
        session,
        *,
        bot_id: int,
        group_id: int,
        ttl_sec: int,
        now: int,
    ) -> None:
        if ttl_sec <= 0 or group_id == 0:
            return
        cutoff = now - ttl_sec
        await session.execute(
            delete(LlmChatMessageRow).where(
                LlmChatMessageRow.bot_id == bot_id,
                LlmChatMessageRow.group_id == group_id,
                LlmChatMessageRow.created_at < cutoff,
            )
        )

    async def _trim_user_window(
        self,
        session,
        *,
        bot_id: int,
        group_id: int,
        user_id: int,
        window: int,
    ) -> None:
        if window <= 0:
            return
        count = (
            await session.execute(
                select(func.count())
                .select_from(LlmChatMessageRow)
                .where(
                    LlmChatMessageRow.bot_id == bot_id,
                    LlmChatMessageRow.group_id == group_id,
                    LlmChatMessageRow.user_id == user_id,
                )
            )
        ).scalar_one()
        overflow = int(count) - window
        if overflow <= 0:
            return
        stale_ids = (
            (
                await session.execute(
                    select(LlmChatMessageRow.id)
                    .where(
                        LlmChatMessageRow.bot_id == bot_id,
                        LlmChatMessageRow.group_id == group_id,
                        LlmChatMessageRow.user_id == user_id,
                    )
                    .order_by(LlmChatMessageRow.created_at.asc(), LlmChatMessageRow.id.asc())
                    .limit(overflow)
                )
            )
            .scalars()
            .all()
        )
        if stale_ids:
            await session.execute(delete(LlmChatMessageRow).where(LlmChatMessageRow.id.in_(stale_ids)))
