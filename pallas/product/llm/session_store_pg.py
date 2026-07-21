from __future__ import annotations

import time

from sqlalchemy import delete, func, select

from pallas.core.foundation.db.repository_pg import LlmChatMessageRow, get_session
from pallas.product.llm.session_models import ALLOWED_ROLES, LlmChatRole, LlmChatTurn, LlmHistorySessionSummary


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
        stmt = (
            select(
                LlmChatMessageRow.bot_id,
                LlmChatMessageRow.group_id,
                LlmChatMessageRow.user_id,
                func.count().label("turn_count"),
                func.min(LlmChatMessageRow.created_at).label("first_created_at"),
                func.max(LlmChatMessageRow.created_at).label("last_created_at"),
            )
            .group_by(
                LlmChatMessageRow.bot_id,
                LlmChatMessageRow.group_id,
                LlmChatMessageRow.user_id,
            )
            .order_by(func.max(LlmChatMessageRow.created_at).desc())
            .limit(limit)
        )

        if bot_id is not None:
            stmt = stmt.where(LlmChatMessageRow.bot_id == int(bot_id))
        if group_id is not None:
            stmt = stmt.where(LlmChatMessageRow.group_id == int(group_id))
        if user_id is not None:
            stmt = stmt.where(LlmChatMessageRow.user_id == int(user_id))

        async with get_session(read_only=True) as session:
            rows = (await session.execute(stmt)).all()

            out: list[LlmHistorySessionSummary] = []
            for row in rows:
                latest_stmt = (
                    select(LlmChatMessageRow)
                    .where(
                        LlmChatMessageRow.bot_id == int(row.bot_id),
                        LlmChatMessageRow.group_id == int(row.group_id),
                        LlmChatMessageRow.user_id == int(row.user_id),
                    )
                    .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
                    .limit(1)
                )
                latest = (await session.execute(latest_stmt)).scalars().first()
                if latest is None:
                    continue
                role = latest.role if latest.role in ALLOWED_ROLES else "user"
                out.append(
                    LlmHistorySessionSummary(
                        session_key=f"{int(row.bot_id)}:{int(row.group_id)}:{int(row.user_id)}",
                        bot_id=int(row.bot_id),
                        group_id=int(row.group_id),
                        user_id=int(row.user_id),
                        turn_count=int(row.turn_count or 0),
                        first_created_at=int(row.first_created_at or 0),
                        last_created_at=int(row.last_created_at or 0),
                        last_role=role,
                        last_content=str(latest.content or ""),
                    )
                )
        return out

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
    ) -> bool:
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
