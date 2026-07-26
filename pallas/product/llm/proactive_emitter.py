"""主动/定时消息统一出口（heartbeat / proactive）。"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nonebot import logger

ProactiveHandler = Callable[[dict[str, Any]], Awaitable[None]]

_handlers: list[tuple[str, ProactiveHandler]] = []
_last_emit_at: dict[str, float] = {}
_cooldown_sec = 30.0
_daily_counts: dict[tuple[int, str], int] = {}
_daily_limit = 3


@dataclass(slots=True)
class ProactiveEmitContext:
    source: str
    group_id: int | None = None
    user_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def register_proactive_handler(name: str, handler: ProactiveHandler) -> None:
    key = (name or "").strip()
    if not key:
        return
    _handlers[:] = [(n, h) for n, h in _handlers if n != key]
    _handlers.append((key, handler))


def proactive_cooldown_remaining(source: str) -> float:
    last = _last_emit_at.get(source, 0.0)
    remain = _cooldown_sec - (time.monotonic() - last)
    return max(0.0, remain)


async def emit_proactive(ctx: ProactiveEmitContext) -> bool:
    """单出口：与 governance 冷却共用限流键（按 source）。"""
    if proactive_cooldown_remaining(ctx.source) > 0:
        logger.debug("proactive skipped cooldown source={}", ctx.source)
        return False
    payload = {
        "source": ctx.source,
        "group_id": ctx.group_id,
        "user_id": ctx.user_id,
        "metadata": dict(ctx.metadata),
    }
    for name, handler in _handlers:
        try:
            await handler(payload)
        except Exception:
            logger.exception("proactive handler failed name={}", name)
    _last_emit_at[ctx.source] = time.monotonic()
    return True


def proactive_daily_count(group_id: int) -> int:
    return _daily_counts.get((int(group_id), date.today().isoformat()), 0)


def reset_proactive_budget_for_tests() -> None:
    _daily_counts.clear()


async def emit_group_proactive(ctx: ProactiveEmitContext) -> bool:
    if ctx.group_id is None or int(ctx.group_id) <= 0:
        return False
    key = (int(ctx.group_id), date.today().isoformat())
    if _daily_counts.get(key, 0) >= _daily_limit:
        return False
    emitted = await emit_proactive(ctx)
    if emitted:
        _daily_counts[key] = _daily_counts.get(key, 0) + 1
    return emitted
