"""PostgreSQL BlackList Repository"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.repository_pg.lifecycle import _strip_null_deep
from pallas.core.foundation.db.repository_pg.schema import BlackListRow

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import BlackList


def row_to_blacklist(row: BlackListRow):
    from pallas.core.foundation.db.modules import BlackList

    return BlackList.model_construct(
        group_id=row.group_id,
        answers=list(row.answers),
        answers_reserve=list(row.answers_reserve),
    )


class PgBlackListRepository:
    async def find_all(self):
        async with _repo.get_session() as session:
            result = await session.execute(select(BlackListRow))
            rows = result.scalars().all()
            return [row_to_blacklist(r) for r in rows]

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        """原子 upsert，基于 group_id 唯一约束。"""
        cleaned = _strip_null_deep(answers)
        async with _repo.get_session() as session:
            stmt = pg_insert(BlackListRow).values(group_id=group_id, answers=cleaned, answers_reserve=[])
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id"],
                set_={"answers": stmt.excluded.answers},
            )
            await session.execute(stmt)
            await session.commit()

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        cleaned = _strip_null_deep(answers)
        async with _repo.get_session() as session:
            stmt = pg_insert(BlackListRow).values(group_id=group_id, answers=[], answers_reserve=cleaned)
            stmt = stmt.on_conflict_do_update(
                index_elements=["group_id"],
                set_={"answers_reserve": stmt.excluded.answers_reserve},
            )
            await session.execute(stmt)
            await session.commit()

    async def upsert_many_blacklist(self, entries: list[BlackList]) -> None:
        """单事务批量 upsert 多群黑名单，避免 shutdown 收尾时逐群串行 commit。"""
        if not entries:
            return
        stmt = pg_insert(BlackListRow).values([
            {
                "group_id": e.group_id,
                "answers": _strip_null_deep(list(e.answers)),
                "answers_reserve": _strip_null_deep(list(e.answers_reserve)),
            }
            for e in entries
        ])
        stmt = stmt.on_conflict_do_update(
            index_elements=["group_id"],
            set_={"answers": stmt.excluded.answers, "answers_reserve": stmt.excluded.answers_reserve},
        )
        async with _repo.get_session() as session:
            await session.execute(stmt)
            await session.commit()
