"""LLM tool 执行上下文（群/用户）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolInvokeContext:
    bot_id: int
    group_id: int | None
    user_id: int

    @classmethod
    def from_payload(cls, payload: dict) -> ToolInvokeContext | None:
        bot_raw = payload.get("bot_id")
        user_raw = payload.get("user_id")
        if bot_raw is None or user_raw is None:
            return None
        try:
            bot_id = int(bot_raw)
            user_id = int(user_raw)
        except (TypeError, ValueError):
            return None
        group_raw = payload.get("group_id")
        group_id = int(group_raw) if group_raw is not None else None
        return cls(bot_id=bot_id, group_id=group_id, user_id=user_id)
