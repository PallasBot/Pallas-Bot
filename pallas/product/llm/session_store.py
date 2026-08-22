from __future__ import annotations

import hashlib
import time
from typing import Any

from nonebot import logger

from pallas.core.foundation.logging import log_rate_limited
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
from pallas.product.llm.session_backend import resolve_session_backend, session_store_backend_ready
from pallas.product.llm.session_models import (
    ALLOWED_ROLES,
    LlmChatRole,
    LlmChatTurn,
    LlmHistorySessionDetail,
    LlmHistorySessionSummary,
    LlmSessionScope,
    is_private_scope,
    normalize_group_scope,
)
from pallas.product.persona.prompt_guard import normalize_enum, sanitize_prompt_block, sanitize_prompt_literal

# Backward-compatible alias used by older imports/tests.
_ALLOWED_ROLES = ALLOWED_ROLES


def is_llm_session_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_session_enabled and session_store_backend_ready()


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
    role_key = normalize_enum(role, ALLOWED_ROLES, "user")
    raw = content
    if role_key == "user":
        cfg = get_llm_config()
        if cfg.llm_session_strip_vision_enabled:
            from pallas.product.llm.vision_content import strip_vision_segments_for_history

            raw = strip_vision_segments_for_history(raw)
    if role_key == "assistant":
        return sanitize_prompt_literal(raw, max_len=max_len)
    return sanitize_prompt_block(raw, max_len=max_len)


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
    role_key = normalize_enum(role, ALLOWED_ROLES, "user")
    safe_content = sanitize_stored_content(role_key, content, max_len=cfg.llm_session_max_content_len)
    if not safe_content:
        return False

    scope_gid = normalize_group_scope(group_id)
    ttl = user_ttl_seconds(scope_gid, cfg)
    return await resolve_session_backend().append_message(
        int(bot_id),
        scope_gid,
        int(user_id),
        role_key,  # type: ignore[arg-type]
        safe_content,
        ttl_sec=ttl,
        window=cfg.llm_session_user_storage_window,
    )


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
    turns = await resolve_session_backend().list_user_messages(
        int(bot_id),
        scope_gid,
        int(user_id),
        limit=max_items + 2,
        ttl_sec=ttl,
    )
    # 摘要消息（【此前对话摘要】）始终保留在读取窗口内，优先于同窗口的普通旧消息
    summary_index = next(
        (i for i, turn in enumerate(turns) if "【此前对话摘要】" in str(turn.content or "")),
        None,
    )
    if summary_index is None or summary_index < max_items:
        return turns[:max_items]
    turns = list(turns)
    summary = turns.pop(summary_index)
    kept = turns[-(max_items - 1) :]
    return [summary, *kept]


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
    return await resolve_session_backend().list_group_ambient(
        int(bot_id),
        scope_gid,
        limit=max_items,
        ttl_sec=ttl,
    )


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
    return await resolve_session_backend().list_history_sessions(
        bot_id=int(bot_id) if bot_id is not None else None,
        group_id=normalize_group_scope(group_id) if group_id is not None else None,
        user_id=int(user_id) if user_id is not None else None,
        limit=max_items,
    )


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


def format_group_ambient_block_with_snapshot(
    turns: list[LlmChatTurn],
    *,
    bot_id: int,
    group_id: int | None,
    max_len: int,
) -> tuple[str, list[dict[str, object]]]:
    if not turns:
        return "", []
    header = "【群环境摘录】"
    block = sanitize_prompt_block(header, max_len=max_len)
    if block != header:
        return block, []
    snapshot: list[dict[str, object]] = []
    scope = normalize_group_scope(group_id)
    for turn in turns:
        raw = str(turn.content or "").strip()
        label = "帕拉斯" if turn.role == "assistant" else "群友"
        line = sanitize_prompt_literal(f"{label}：{raw}", max_len=512)
        if not line:
            continue
        text_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        available = max_len - len(block) - 1
        if available <= 0:
            break
        rendered_line = line[:available].rstrip()
        if not rendered_line:
            break
        rendered_text = rendered_line.removeprefix(f"{label}：")
        if rendered_text:
            snapshot.append({
                "turn_id": (
                    f"ambient:{int(bot_id)}:{scope}:{turn.role}:{int(turn.user_id)}:{int(turn.created_at)}:{text_hash}"
                ),
                "user_id": int(turn.user_id),
                "text_hash": text_hash,
                "text_preview": rendered_text[:120],
            })
        block = f"{block}\n{rendered_line}"
        if rendered_line != line:
            break
    return block, snapshot


async def build_llm_chat_messages(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    current_user_text: str,
    *,
    cfg: LlmConfig | None = None,
    include_history: bool = True,
    history_limit: int | None = None,
    include_group_ambient: bool = True,
    ambient_turns_out: list[dict[str, object]] | None = None,
    ambient_message_token_out: list[str] | None = None,
) -> list[ChatCompletionMessage]:
    c = cfg or get_llm_config()
    messages: list[ChatCompletionMessage] = []

    if not can_read_runtime_state(c):
        current = format_user_turn(current_user_text, max_len=c.user_message_max_len)
        if not current:
            return messages
        messages.append(ChatCompletionMessage(role="user", content=current))
        return messages

    if (
        include_history
        and include_group_ambient
        and not is_private_scope(group_id)
        and c.llm_session_group_ambient_enabled
    ):
        ambient = await list_group_ambient_messages(bot_id, group_id, cfg=c)
        ambient = [turn for turn in ambient if turn.user_id != int(user_id)]
        try:
            from pallas.product.llm.injection_feedback import filter_ambient_turns

            ambient = filter_ambient_turns(int(bot_id), normalize_group_scope(group_id), ambient)
        except Exception as exc:
            log_rate_limited(
                logger,
                "warning",
                "llm.injection_governance.ambient_filter_failed",
                "ambient injection governance filter failed for bot [{}] and group [{}]: [{}]",
                bot_id,
                normalize_group_scope(group_id),
                exc,
            )
        ambient_block, ambient_snapshot = format_group_ambient_block_with_snapshot(
            ambient,
            bot_id=bot_id,
            group_id=group_id,
            max_len=c.user_message_max_len,
        )
        if ambient_block:
            wrapped = format_user_turn(ambient_block, max_len=c.user_message_max_len)
            if wrapped:
                token_text = "\n".join(str(item["turn_id"]) for item in ambient_snapshot)
                ambient_token = f"ambient:{hashlib.sha256(token_text.encode()).hexdigest()}"
                messages.append(ChatCompletionMessage(role="user", content=wrapped, source_token=ambient_token))
                if ambient_turns_out is not None:
                    ambient_turns_out.extend(ambient_snapshot)
                if ambient_message_token_out is not None:
                    ambient_message_token_out.append(ambient_token)

    if include_history:
        history = await list_user_llm_messages(bot_id, group_id, user_id, limit=history_limit, cfg=c)
        for turn in history:
            item = turn_to_completion_message(turn, max_len=c.user_message_max_len)
            if item is not None:
                messages.append(item)

    current = format_user_turn(current_user_text, max_len=c.user_message_max_len)
    if not current:
        return messages
    messages.append(ChatCompletionMessage(role="user", content=current))
    return messages


async def clear_llm_messages(bot_id: int, group_id: int | None) -> int:
    if not is_llm_session_store_available():
        return 0
    scope_gid = normalize_group_scope(group_id)
    return await resolve_session_backend().clear_group(int(bot_id), scope_gid)


async def clear_user_llm_messages(bot_id: int, group_id: int | None, user_id: int) -> int:
    if not is_llm_session_store_available():
        return 0
    scope_gid = normalize_group_scope(group_id)
    return await resolve_session_backend().clear_user(int(bot_id), scope_gid, int(user_id))


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
    scope_gid = normalize_group_scope(group_id)
    summary_content = sanitize_stored_content(
        "user",
        f"【此前对话摘要】\n{safe_summary}",
        max_len=c.llm_session_max_content_len,
    )
    if not summary_content:
        return False
    return await resolve_session_backend().compact_user_with_summary(
        int(bot_id),
        scope_gid,
        int(user_id),
        summary_content,
        keep_messages=keep_messages,
    )
