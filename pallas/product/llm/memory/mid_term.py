"""中期会话摘要（聊天回想）浏览：从会话消息中提取 compact 摘要块。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.session_models import normalize_group_scope
from pallas.product.llm.session_store import list_llm_history_sessions, list_user_llm_messages

MID_TERM_PREFIX = "【此前对话摘要】"


async def list_mid_term_summaries(
    *,
    bot_id: int,
    group_id: int | None = None,
    user_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    max_items = max(1, min(int(limit), 200))
    sessions = await list_llm_history_sessions(
        bot_id=int(bot_id),
        group_id=normalize_group_scope(group_id) if group_id is not None else None,
        user_id=int(user_id) if user_id is not None else None,
        limit=max_items,
    )
    out: list[dict[str, Any]] = []
    for session in sessions:
        sid_bot = int(getattr(session, "bot_id", 0) if not isinstance(session, dict) else session.get("bot_id") or 0)
        sid_group = int(
            getattr(session, "group_id", 0) if not isinstance(session, dict) else session.get("group_id") or 0
        )
        sid_user = int(getattr(session, "user_id", 0) if not isinstance(session, dict) else session.get("user_id") or 0)
        turns = await list_user_llm_messages(sid_bot, sid_group, sid_user, limit=80)
        for turn in turns:
            content = str(turn.content or "").strip()
            if not content.startswith(MID_TERM_PREFIX):
                continue
            body = content[len(MID_TERM_PREFIX) :].strip()
            if body.startswith("\n"):
                body = body[1:].strip()
            out.append({
                "bot_id": sid_bot,
                "group_id": sid_group,
                "user_id": sid_user,
                "created_at": int(turn.created_at or 0),
                "summary": body or content,
                "raw": content,
            })
            if len(out) >= max_items:
                return out
    return out
