"""PostgreSQL Repository 实现（预留接口，尚未实现）"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.common.db.modules import BlackList, Context, Message


class PgContextRepository:
    """PostgreSQL 版 ContextRepository 实现（预留）"""

    async def find_by_keywords(self, keywords: str) -> Context | None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def save(self, context: Context) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def insert(self, context: Context) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        raise NotImplementedError("PostgreSQL 后端尚未实现")


class PgMessageRepository:
    """PostgreSQL 版 MessageRepository 实现（预留）"""

    async def bulk_insert(self, messages: list[Message]) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")


class PgBlackListRepository:
    """PostgreSQL 版 BlackListRepository 实现（预留）"""

    async def find_all(self) -> list[BlackList]:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")
