"""会话运维：统计、试聊注入、清空与摘要压缩的控制台门面。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.config import get_llm_config
from pallas.product.llm.session_models import LlmChatRole, normalize_group_scope
from pallas.product.llm.session_store import (
    append_llm_message,
    clear_llm_messages,
    clear_user_llm_messages,
    compact_user_llm_history_with_summary,
    is_llm_session_store_available,
    list_llm_history_sessions,
)


async def build_llm_history_stats(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    sessions = await list_llm_history_sessions(
        bot_id=bot_id,
        group_id=group_id,
        limit=max(1, min(int(limit), 500)),
    )
    group_count = 0
    private_count = 0
    turn_total = 0
    last_activity = 0
    for item in sessions:
        gid = int(getattr(item, "group_id", 0) if not isinstance(item, dict) else item.get("group_id") or 0)
        turns = int(getattr(item, "turn_count", 0) if not isinstance(item, dict) else item.get("turn_count") or 0)
        last_at = int(
            getattr(item, "last_created_at", 0) if not isinstance(item, dict) else item.get("last_created_at") or 0
        )
        turn_total += turns
        last_activity = max(last_activity, last_at)
        if gid == 0:
            private_count += 1
        else:
            group_count += 1
    cfg = get_llm_config()
    return {
        "available": is_llm_session_store_available(),
        "session_enabled": bool(cfg.llm_session_enabled),
        "session_count": len(sessions),
        "group_session_count": group_count,
        "private_session_count": private_count,
        "turn_total": turn_total,
        "last_activity_at": last_activity,
        "user_window": int(cfg.llm_session_user_window),
        "group_window": int(cfg.llm_session_group_window),
        "summary_enabled": bool(cfg.llm_session_summary_enabled),
        "summary_threshold": int(cfg.llm_session_summary_threshold),
        "summary_keep_messages": int(cfg.llm_session_summary_keep_messages),
    }


async def clear_llm_history_session(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int | None = None,
) -> dict[str, Any]:
    if user_id is not None:
        deleted = await clear_user_llm_messages(int(bot_id), group_id, int(user_id))
        return {
            "scope": "user",
            "bot_id": int(bot_id),
            "group_id": normalize_group_scope(group_id),
            "user_id": int(user_id),
            "deleted": int(deleted),
        }
    deleted = await clear_llm_messages(int(bot_id), group_id)
    return {
        "scope": "group",
        "bot_id": int(bot_id),
        "group_id": normalize_group_scope(group_id),
        "deleted": int(deleted),
    }


async def inject_llm_history_message(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    content: str,
    role: LlmChatRole = "user",
) -> dict[str, Any]:
    ok = await append_llm_message(int(bot_id), group_id, int(user_id), role, content)
    return {
        "ok": bool(ok),
        "bot_id": int(bot_id),
        "group_id": normalize_group_scope(group_id),
        "user_id": int(user_id),
        "role": role,
    }


async def compact_llm_history_session(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    summary: str,
    keep_messages: int | None = None,
) -> dict[str, Any]:
    cfg = get_llm_config()
    keep = int(keep_messages) if keep_messages is not None else int(cfg.llm_session_summary_keep_messages)
    ok = await compact_user_llm_history_with_summary(
        int(bot_id),
        group_id,
        int(user_id),
        summary,
        keep_messages=max(1, keep),
        cfg=cfg,
    )
    return {
        "ok": bool(ok),
        "bot_id": int(bot_id),
        "group_id": normalize_group_scope(group_id),
        "user_id": int(user_id),
        "keep_messages": max(1, keep),
    }
