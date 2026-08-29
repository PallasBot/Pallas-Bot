"""群成员图片发送统计的 PostgreSQL/SQLite 仓储。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pallas.core.foundation.db.modules import UserStickerStat
from pallas.core.foundation.db.repository_pg import UserStickerStatRow, get_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class UserStickerStatRepository:
    """按 ``(group_id, user_id, content_hash)`` 聚合的发送次数统计。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory

    def session(self):
        return self._session_factory() if self._session_factory is not None else get_session()

    @staticmethod
    def increment_statement(
        *,
        group_id: int,
        user_id: int,
        content_hash: str,
        sent_at: int,
        now: int,
        dialect_name: str,
        count: int = 1,
    ):
        values = {
            "group_id": int(group_id),
            "user_id": int(user_id),
            "content_hash": content_hash,
            "send_count": int(count),
            "last_sent_at": int(sent_at),
            "updated_at": int(now),
        }
        if dialect_name == "postgresql":
            stmt = pg_insert(UserStickerStatRow).values(**values)
        elif dialect_name == "sqlite":
            stmt = sqlite_insert(UserStickerStatRow).values(**values)
        else:
            raise RuntimeError(f"unsupported user sticker stat dialect: {dialect_name}")
        return stmt.on_conflict_do_update(
            index_elements=["group_id", "user_id", "content_hash"],
            set_={
                "send_count": UserStickerStatRow.send_count + int(count),
                "last_sent_at": int(sent_at),
                "updated_at": int(now),
            },
        )

    @staticmethod
    def _row_to_stat(row: UserStickerStatRow) -> UserStickerStat:
        return UserStickerStat.model_construct(
            group_id=int(row.group_id),
            user_id=int(row.user_id),
            content_hash=str(row.content_hash),
            send_count=int(row.send_count),
            last_sent_at=int(row.last_sent_at),
            updated_at=int(row.updated_at),
        )

    async def increment(self, *, group_id: int, user_id: int, content_hash: str, sent_at: int, count: int = 1) -> None:
        now = int(time.time())
        async with self.session() as session:
            dialect_name = session.get_bind().dialect.name
            await session.execute(
                self.increment_statement(
                    group_id=group_id,
                    user_id=user_id,
                    content_hash=content_hash,
                    sent_at=sent_at,
                    now=now,
                    dialect_name=dialect_name,
                    count=count,
                )
            )
            await session.commit()

    async def get(self, *, group_id: int, user_id: int, content_hash: str) -> UserStickerStat | None:
        async with self.session() as session:
            row = (
                await session.execute(
                    select(UserStickerStatRow).where(
                        UserStickerStatRow.group_id == int(group_id),
                        UserStickerStatRow.user_id == int(user_id),
                        UserStickerStatRow.content_hash == content_hash,
                    )
                )
            ).scalar_one_or_none()
            return self._row_to_stat(row) if row is not None else None

    async def list_group_candidates(
        self, *, group_id: int, min_count: int, limit: int | None = 5
    ) -> list[UserStickerStat]:
        """列出群内达到阈值的统计；``limit=None`` 返回全部候选。"""
        async with self.session() as session:
            statement = (
                select(UserStickerStatRow)
                .where(
                    UserStickerStatRow.group_id == int(group_id),
                    UserStickerStatRow.send_count >= int(min_count),
                )
                .order_by(UserStickerStatRow.send_count.desc(), UserStickerStatRow.last_sent_at.desc())
            )
            if limit is not None:
                statement = statement.limit(max(1, min(int(limit), 100)))
            rows = (await session.execute(statement)).scalars().all()
        return [self._row_to_stat(row) for row in rows]

    async def delete_cold(self, *, before_ts: int, max_count: int) -> int:
        async with self.session() as session:
            result = await session.execute(
                delete(UserStickerStatRow).where(
                    UserStickerStatRow.send_count < int(max_count),
                    UserStickerStatRow.updated_at < int(before_ts),
                )
            )
            await session.commit()
        return int(result.rowcount or 0)
