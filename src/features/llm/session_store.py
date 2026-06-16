from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, func, select

from src.features.llm.config import LlmConfig, get_llm_config
from src.features.llm.message_guard import format_user_turn
from src.features.llm.models import ChatCompletionMessage
from src.features.persona.prompt_guard import normalize_enum, sanitize_prompt_block, sanitize_prompt_literal
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


def is_private_scope(group_id: int | None) -> bool:
    return normalize_group_scope(group_id) == 0


def is_llm_session_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_session_enabled and is_postgresql_backend() and is_pg_initialized()


def user_ttl_seconds(group_id: int | None, cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    if is_private_scope(group_id):
        return c.llm_session_private_ttl_sec
    return c.llm_session_user_ttl_sec


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
    return sanitize_prompt_block(content, max_len=max_len)


async def purge_user_ttl(
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


async def purge_group_ttl(
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


async def trim_user_window(
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
    ttl = user_ttl_seconds(scope_gid, cfg)
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
        await purge_user_ttl(
            session,
            bot_id=int(bot_id),
            group_id=scope_gid,
            user_id=int(user_id),
            ttl_sec=ttl,
            now=now,
        )
        await trim_user_window(
            session,
            bot_id=int(bot_id),
            group_id=scope_gid,
            user_id=int(user_id),
            window=cfg.llm_session_user_window,
        )
        if scope_gid != 0:
            await purge_group_ttl(
                session,
                bot_id=int(bot_id),
                group_id=scope_gid,
                ttl_sec=user_ttl_seconds(scope_gid, cfg),
                now=now,
            )
        await session.commit()
    return True


async def list_user_llm_messages(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    limit: int | None = None,
    cfg: LlmConfig | None = None,
) -> list[LlmChatTurn]:
    if not is_llm_session_store_available():
        return []
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    max_items = limit if limit is not None else c.llm_session_user_window
    max_items = max(1, min(max_items, c.llm_session_user_window))
    ttl = user_ttl_seconds(scope_gid, c)

    stmt = (
        select(LlmChatMessageRow)
        .where(
            LlmChatMessageRow.bot_id == int(bot_id),
            LlmChatMessageRow.group_id == scope_gid,
            LlmChatMessageRow.user_id == int(user_id),
        )
        .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
        .limit(max_items)
    )
    if ttl > 0:
        cutoff = int(time.time()) - ttl
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


async def list_group_ambient_messages(
    bot_id: int,
    group_id: int | None,
    *,
    limit: int | None = None,
    cfg: LlmConfig | None = None,
) -> list[LlmChatTurn]:
    if not is_llm_session_store_available():
        return []
    scope_gid = normalize_group_scope(group_id)
    if scope_gid == 0:
        return []
    c = cfg or get_llm_config()
    if not c.llm_session_group_ambient_enabled:
        return []
    max_items = limit if limit is not None else c.llm_session_group_window
    max_items = max(1, min(max_items, c.llm_session_group_window))
    ttl = user_ttl_seconds(scope_gid, c)

    stmt = (
        select(LlmChatMessageRow)
        .where(
            LlmChatMessageRow.bot_id == int(bot_id),
            LlmChatMessageRow.group_id == scope_gid,
        )
        .order_by(LlmChatMessageRow.created_at.desc(), LlmChatMessageRow.id.desc())
        .limit(max_items)
    )
    if ttl > 0:
        cutoff = int(time.time()) - ttl
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


async def list_llm_messages(
    bot_id: int,
    group_id: int | None,
    *,
    limit: int | None = None,
    user_id: int | None = None,
) -> list[LlmChatTurn]:
    if user_id is not None:
        return await list_user_llm_messages(bot_id, group_id, int(user_id), limit=limit)
    return await list_group_ambient_messages(bot_id, group_id, limit=limit)


def turn_to_completion_message(turn: LlmChatTurn, *, max_len: int) -> ChatCompletionMessage | None:
    if turn.role == "assistant":
        content = sanitize_prompt_literal(turn.content, max_len=max_len)
        if not content:
            return None
        return ChatCompletionMessage(role="assistant", content=content)
    content = format_user_turn(turn.content, max_len=max_len)
    if not content:
        return None
    return ChatCompletionMessage(role="user", content=content)


def format_group_ambient_block(turns: list[LlmChatTurn], *, max_len: int) -> str:
    if not turns:
        return ""
    lines: list[str] = []
    for turn in turns:
        label = "帕拉斯" if turn.role == "assistant" else "群友"
        line = sanitize_prompt_literal(f"{label}：{turn.content}", max_len=512)
        if line:
            lines.append(line)
    body = "\n".join(lines)
    return sanitize_prompt_block(f"【群环境摘录】\n{body}", max_len=max_len)


async def build_llm_chat_messages(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    current_user_text: str,
    *,
    cfg: LlmConfig | None = None,
) -> list[ChatCompletionMessage]:
    c = cfg or get_llm_config()
    messages: list[ChatCompletionMessage] = []

    if not is_private_scope(group_id) and c.llm_session_group_ambient_enabled:
        ambient = await list_group_ambient_messages(bot_id, group_id, cfg=c)
        ambient = [turn for turn in ambient if turn.user_id != int(user_id)]
        ambient_block = format_group_ambient_block(ambient, max_len=c.user_message_max_len)
        if ambient_block:
            wrapped = format_user_turn(ambient_block, max_len=c.user_message_max_len)
            if wrapped:
                messages.append(ChatCompletionMessage(role="user", content=wrapped))

    history = await list_user_llm_messages(bot_id, group_id, user_id, cfg=c)
    for turn in history:
        item = turn_to_completion_message(turn, max_len=c.user_message_max_len)
        if item is not None:
            messages.append(item)

    current = format_user_turn(current_user_text, max_len=c.user_message_max_len)
    if not current:
        return messages
    messages.append(ChatCompletionMessage(role="user", content=current))
    return messages


def format_legacy_transcript(messages: list[ChatCompletionMessage]) -> str:
    parts: list[str] = []
    for item in messages:
        text = item.content.strip()
        if not text:
            continue
        if item.role == "assistant":
            parts.append(f"帕拉斯：{text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


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


async def clear_user_llm_messages(bot_id: int, group_id: int | None, user_id: int) -> int:
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
                    LlmChatMessageRow.user_id == int(user_id),
                )
            )
        ).scalar_one()
        await session.execute(
            delete(LlmChatMessageRow).where(
                LlmChatMessageRow.bot_id == int(bot_id),
                LlmChatMessageRow.group_id == scope_gid,
                LlmChatMessageRow.user_id == int(user_id),
            )
        )
        await session.commit()
    return int(count)
