"""PostgreSQL Repository 实现（预留接口，尚未实现）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.common.db.modules import Answer, Ban, BlackList, Context, ImageCache, Message


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

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def append_ban(self, keywords: str, ban: Ban) -> None:
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


class PgConfigRepository:
    """
    PostgreSQL 版 ConfigRepository 实现（预留）。

    通过 (table, primary_key) 绑定到不同配置表，未来实现时可直接用同一份
    SQL 逻辑服务 Bot/Group/User 三种配置。
    """

    def __init__(self, table: str, primary_key: str) -> None:
        self._table = table
        self._primary_key = primary_key

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def upsert_field(self, key_id: int, field: str, value: Any) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def invalidate_cache(self) -> None:
        # PG 无 Beanie 级缓存，no-op
        return None


class PgImageCacheRepository:
    """PostgreSQL 版 ImageCacheRepository 实现（预留）"""

    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def insert(self, cache: ImageCache) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def save(self, cache: ImageCache) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def delete_old(self, before_date: int) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")

    async def delete_low_ref(self, ref_threshold: int) -> None:
        raise NotImplementedError("PostgreSQL 后端尚未实现")
