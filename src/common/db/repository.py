from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.common.db.modules import BlackList, Context, Message


@runtime_checkable
class ContextRepository(Protocol):
    async def find_by_keywords(self, keywords: str) -> Context | None:
        """Find a Context document by its keywords field."""
        ...

    async def save(self, context: Context) -> None:
        """Save/update an existing Context document."""
        ...

    async def insert(self, context: Context) -> None:
        """Insert a new Context document."""
        ...

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        """Delete Context documents older than expiration with trigger_count below threshold."""
        ...

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        """Find Context documents that need cleanup (high trigger_count or old clear_time)."""
        ...


@runtime_checkable
class MessageRepository(Protocol):
    async def bulk_insert(self, messages: list[Message]) -> None:
        """Insert multiple Message documents at once."""
        ...


@runtime_checkable
class BlackListRepository(Protocol):
    async def find_all(self) -> list[BlackList]:
        """Retrieve all BlackList documents."""
        ...

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        """Upsert BlackList answers for a group. Create if not exists, update if exists."""
        ...

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        """Upsert BlackList answers_reserve for a group. Create if not exists, update if exists."""
        ...
