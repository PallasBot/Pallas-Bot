from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, func, select

from src.features.llm.config import get_llm_config
from src.features.llm.message_guard import sanitize_user_message
from src.features.persona.prompt_guard import normalize_enum, sanitize_prompt_literal
from src.foundation.db.repository_pg import LlmChatMessageRow, get_session, is_pg_initialized
from src.foundation.db.runtime import is_postgresql_backend

LlmChatRole = Literal["user", "assistant"]
_ALLOWED_ROLES = frozenset({"user", "assistant"})


class LlmChatTurn(BaseModel):
    role: LlmChatRole
    content: str
    user_id: int
    created_at: int


class LlmSessionScope(BaseModel):
    bot_id: int
    group_id: int = 0
    user_id: int | None = None


def normalize_group_scope(group_id: int | None) -> int:
    return int(group_id) if group_id is not None else 0


def is_llm_session_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_session_enabled and is_postgresql_backend() and is_pg_initialized()


def session_scope(bot_id: int, group_id: int | None, user_id: int | None = None) -> LlmSessionScope:
    return LlmSessionScope(
        bot_id=int(bot_id),
        group_id=normalize_group_scope(group_id),
        user_id=int(user_id) if user_id is not None else None,
    )


def sanitize_stored_content(role: str, content: str, *, max_len: int) -> str:
    role_key = normalize_enum(role, _ALLOWED_ROLES, "user")
    if role_key == "assistant":
        return sanitize_prompt_literal(content, max_len=max_len)
    return sanitize_user_message(content, max_len=max_len)


async def append_llm_message(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    role: LlmChatRole,
    content: str,
) -> bool:
    if not is_llm_session_store_available():
        return False
    cfg = get_llm_config()
    role_key = normalize_enum(role, _ALLOWED_ROLES, "user")
    safe_content = sanitize_stored_content(role_key, content, max_len=cfg.llm_session_max_content_len)
    if not safe_content:
        return False

    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    async with get_session() as session:
        session.add(
            LlmChatMessageRow(
                bot_id=int(bot_id),
                group_id=scope_gid,
                user_id=int(user_id),
                role=role_key,
                content=safe_content,
                created_at=now,
            )
        )
        await session.flush()
        if cfg.llm_session_user_ttl_sec > 0:
            cutoff = now - cfg.llm_session_user_ttl_sec
            await session.execute(
                delete(LlmChatMessageRow).where(
                    LlmChatMessageRow.bot_id == int(bot_id),
                    LlmChatMessageRow.group_id == scope_gid,
                    LlmChatMessageRow.user_id == int(user_id),
                    LlmChatMessageRow.created_at < cutoff,
                )
            )
        await trim_group_window(session, bot_id=int(bot_id), group_id=scope_gid, window=cfg.llm_session_group_window)
        await session.commit()
    return True


async def trim_group_window(session, *, bot_id: int, group_id: int, window: int) -> None:
    if window <= 0:
        return
    count = (
        await session.execute(
            select(func.count())
            .select_from(LlmChatMessageRow)
            .where(
                LlmChatMessageRow.bot_id == bot_id,
                LlmChatMessageRow.group_id == group_id,
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


async def list_llm_messages(
    bot_id: int,
    group_id: int | None,
    *,
    limit: int | None = None,
    user_id: int | None = None,
) -> list[LlmChatTurn]:
    if not is_llm_session_store_available():
        return []
    cfg = get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    max_items = limit if limit is not None else cfg.llm_session_group_window
    max_items = max(1, min(max_items, cfg.llm_session_group_window))

    stmt = (
        select(LlmChatMessageRow)
        .where(
            LlmChatMessageRow.bot_id == int(bot_id),
            LlmChatMessageRow.group_id == scope_gid,
        )
        .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
        .limit(max_items)
    )
    if user_id is not None:
        stmt = stmt.where(LlmChatMessageRow.user_id == int(user_id))
        if cfg.llm_session_user_ttl_sec > 0:
            cutoff = int(time.time()) - cfg.llm_session_user_ttl_sec
            stmt = stmt.where(LlmChatMessageRow.created_at >= cutoff)

    async with get_session(read_only=True) as session:
        rows = (await session.execute(stmt)).scalars().all()

    return [
        LlmChatTurn(
            role=row.role if row.role in _ALLOWED_ROLES else "user",
            content=row.content,
            user_id=int(row.user_id),
            created_at=int(row.created_at),
        )
        for row in reversed(rows)
    ]


async def clear_llm_messages(bot_id: int, group_id: int | None) -> int:
    if not is_llm_session_store_available():
        return 0
    scope_gid = normalize_group_scope(group_id)
    async with get_session() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(LlmChatMessageRow)
                .where(
                    LlmChatMessageRow.bot_id == int(bot_id),
                    LlmChatMessageRow.group_id == scope_gid,
                )
            )
        ).scalar_one()
        await session.execute(
            delete(LlmChatMessageRow).where(
                LlmChatMessageRow.bot_id == int(bot_id),
                LlmChatMessageRow.group_id == scope_gid,
            )
        )
        await session.commit()
    return int(count)
