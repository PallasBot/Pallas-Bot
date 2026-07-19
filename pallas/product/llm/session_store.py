from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from pallas.core.foundation.db.repository_pg import LlmChatMessageRow, get_session, is_pg_initialized
from pallas.core.foundation.db.runtime import is_postgresql_backend
from pallas.product.llm.behavior import infer_behavior_feedback
from pallas.product.llm.behavior_store import (
    behavior_run_public_dict,
    list_behavior_runs_for_session,
    settle_behavior_run_outcome,
    update_behavior_run_annotation,
)
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.kernel.memory_governance import can_read_runtime_state
from pallas.product.llm.message_guard import format_user_turn
from pallas.product.llm.models import ChatCompletionMessage
from pallas.product.persona.prompt_guard import normalize_enum, sanitize_prompt_block, sanitize_prompt_literal

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


class LlmHistorySessionSummary(BaseModel):
    session_key: str
    bot_id: int
    group_id: int
    user_id: int
    turn_count: int
    first_created_at: int
    last_created_at: int
    last_role: LlmChatRole
    last_content: str


class LlmHistorySessionDetail(BaseModel):
    session: LlmHistorySessionSummary
    turns: list[LlmChatTurn]
    behavior_runs: list[dict[str, Any]] = Field(default_factory=list)
    feedback_entries: list[dict[str, Any]] = Field(default_factory=list)


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
    raw = content
    if role_key == "user":
        cfg = get_llm_config()
        if cfg.llm_session_strip_vision_enabled:
            from pallas.product.llm.vision_content import strip_vision_segments_for_history

            raw = strip_vision_segments_for_history(raw)
    if role_key == "assistant":
        return sanitize_prompt_literal(raw, max_len=max_len)
    return sanitize_prompt_block(raw, max_len=max_len)


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


async def list_llm_history_sessions(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
    limit: int = 50,
) -> list[LlmHistorySessionSummary]:
    if not is_llm_session_store_available():
        return []

    max_items = max(1, min(int(limit), 200))
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
        .limit(max_items)
    )

    if bot_id is not None:
        stmt = stmt.where(LlmChatMessageRow.bot_id == int(bot_id))
    if group_id is not None:
        stmt = stmt.where(LlmChatMessageRow.group_id == normalize_group_scope(group_id))
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
            role = latest.role if latest.role in _ALLOWED_ROLES else "user"
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


async def get_llm_history_session_detail(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    limit: int = 100,
) -> LlmHistorySessionDetail | None:
    turns = await list_user_llm_messages(
        int(bot_id),
        normalize_group_scope(group_id),
        int(user_id),
        limit=max(1, min(int(limit), 200)),
    )
    if not turns:
        return None
    ambient_turns = await list_group_ambient_messages(
        int(bot_id),
        normalize_group_scope(group_id),
        limit=50,
    )
    ambient_turns = [item for item in ambient_turns if int(item.user_id) != int(user_id)]
    summary_rows = await list_llm_history_sessions(
        bot_id=int(bot_id),
        group_id=normalize_group_scope(group_id),
        user_id=int(user_id),
        limit=1,
    )
    if not summary_rows:
        return None
    behavior_runs = list(
        list_behavior_runs_for_session(
            bot_id=int(bot_id),
            group_id=normalize_group_scope(group_id),
            user_id=int(user_id),
            limit=50,
        )
    )
    resolved_runs: list[dict[str, Any]] = []
    now = int(time.time())
    for item in behavior_runs:
        outcome, payload = infer_behavior_feedback(run=item, turns=turns, ambient_turns=ambient_turns, now=now)
        if outcome is not None:
            updated = settle_behavior_run_outcome(
                item.request_id,
                final_outcome=outcome,
                auto_feedback_payload=payload,
            )
            if updated is not None:
                item = updated
        resolved_runs.append(behavior_run_public_dict(item))
    from pallas.product.llm.repeater_feedback import list_feedback_entries_for_session

    feedback_rows = list_feedback_entries_for_session(
        bot_id=int(bot_id),
        group_id=int(normalize_group_scope(group_id)),
        user_id=int(user_id),
        limit=100,
    )
    feedback_entries = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item) for item in feedback_rows
    ]
    return LlmHistorySessionDetail(
        session=summary_rows[0],
        turns=turns,
        behavior_runs=resolved_runs,
        feedback_entries=feedback_entries,
    )


async def update_llm_behavior_annotation(
    *,
    request_id: str,
    labels: list[str],
    final_outcome: str | None = None,
    disabled: bool | None = None,
):
    return update_behavior_run_annotation(
        request_id,
        labels=labels,
        final_outcome=final_outcome,
        disabled=disabled,
    )


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

    if not can_read_runtime_state(c):
        current = format_user_turn(current_user_text, max_len=c.user_message_max_len)
        if not current:
            return messages
        messages.append(ChatCompletionMessage(role="user", content=current))
        return messages

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


async def compact_user_llm_history_with_summary(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    summary: str,
    *,
    keep_messages: int,
    cfg: LlmConfig | None = None,
) -> bool:
    if not is_llm_session_store_available():
        return False
    c = cfg or get_llm_config()
    safe_summary = sanitize_prompt_block(summary, max_len=c.llm_session_max_content_len)
    if not safe_summary:
        return False
    keep = max(2, int(keep_messages))
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    async with get_session() as session:
        rows = (
            (
                await session.execute(
                    select(LlmChatMessageRow)
                    .where(
                        LlmChatMessageRow.bot_id == int(bot_id),
                        LlmChatMessageRow.group_id == scope_gid,
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
                group_id=scope_gid,
                user_id=int(user_id),
                role="user",
                content=sanitize_stored_content(
                    "user",
                    f"【此前对话摘要】\n{safe_summary}",
                    max_len=c.llm_session_max_content_len,
                ),
                created_at=anchor_time,
            )
        )
        await session.commit()
    return True
