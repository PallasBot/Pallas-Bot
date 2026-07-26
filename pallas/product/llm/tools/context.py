"""LLM tool 执行上下文（群/用户）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolInvokeContext:
    bot_id: int
    group_id: int | None
    user_id: int
    source_segments: tuple[dict[str, Any], ...] = ()

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
        source_segments = _parse_source_segments(payload.get("command_source_segments"))
        return cls(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            source_segments=source_segments,
        )


def _parse_source_segments(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(dict(item) for item in raw if isinstance(item, dict) and item.get("type"))
