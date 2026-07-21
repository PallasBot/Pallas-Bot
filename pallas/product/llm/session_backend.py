from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pallas.product.llm.session_models import LlmChatRole, LlmChatTurn, LlmHistorySessionSummary


class LlmSessionMessageBackend(Protocol):
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
    ) -> bool: ...

    async def list_user_messages(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        *,
        limit: int,
        ttl_sec: int,
    ) -> list[LlmChatTurn]: ...

    async def list_group_ambient(
        self,
        bot_id: int,
        group_id: int,
        *,
        limit: int,
        ttl_sec: int,
    ) -> list[LlmChatTurn]: ...

    async def list_history_sessions(
        self,
        *,
        bot_id: int | None,
        group_id: int | None,
        user_id: int | None,
        limit: int,
    ) -> list[LlmHistorySessionSummary]: ...

    async def clear_group(self, bot_id: int, group_id: int) -> int: ...

    async def clear_user(self, bot_id: int, group_id: int, user_id: int) -> int: ...

    async def compact_user_with_summary(
        self,
        bot_id: int,
        group_id: int,
        user_id: int,
        summary_content: str,
        *,
        keep_messages: int,
    ) -> bool: ...


def resolve_session_backend() -> LlmSessionMessageBackend:
    from pallas.core.foundation.db.runtime import is_mongodb_backend, is_postgresql_backend

    if is_postgresql_backend():
        from pallas.product.llm.session_store_pg import PgLlmSessionMessageBackend

        return PgLlmSessionMessageBackend()
    if is_mongodb_backend():
        from pallas.product.llm.session_store_mongo import MongoLlmSessionMessageBackend

        return MongoLlmSessionMessageBackend()
    raise RuntimeError("no llm session backend for current db_backend")


def session_store_backend_ready() -> bool:
    """当前 db_backend 的持久化存储是否已就绪（PG 或 Mongo）。"""
    from pallas.core.foundation.db import runtime_storage_ready
    from pallas.core.foundation.db.repository_pg import is_pg_initialized
    from pallas.core.foundation.db.runtime import is_mongodb_backend, is_postgresql_backend

    if is_postgresql_backend():
        return is_pg_initialized()
    if is_mongodb_backend():
        return runtime_storage_ready("mongodb")
    return False


# 记忆 / 关系便签等产品侧存储共用同一就绪判断。
llm_product_storage_ready = session_store_backend_ready
