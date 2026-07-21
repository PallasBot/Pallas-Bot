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


_session_backend_cache: dict[str, LlmSessionMessageBackend] = {}


def clear_session_backend_cache() -> None:
    """测试或热切换 db_backend 时清空进程内缓存。"""
    _session_backend_cache.clear()


def resolve_session_backend() -> LlmSessionMessageBackend:
    from pallas.core.foundation.db.runtime import get_db_backend, is_mongodb_backend, is_postgresql_backend

    backend_name = get_db_backend()
    cached = _session_backend_cache.get(backend_name)
    if cached is not None:
        return cached

    if is_postgresql_backend(backend_name):
        from pallas.product.llm.session_store_pg import PgLlmSessionMessageBackend

        instance: LlmSessionMessageBackend = PgLlmSessionMessageBackend()
    elif is_mongodb_backend(backend_name):
        from pallas.product.llm.session_store_mongo import MongoLlmSessionMessageBackend

        instance = MongoLlmSessionMessageBackend()
    else:
        raise RuntimeError("no llm session backend for current db_backend")
    _session_backend_cache[backend_name] = instance
    return instance


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
