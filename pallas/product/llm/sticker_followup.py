"""LLM 回复后的图片跟随判定。"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_LAST_REPEATER_IMAGE_SENT_AT: dict[int, float] = {}
_RECENT_REPEATER_IMAGES: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=8))
_STICKER_FOLLOWUP_SCHEDULED_AT: dict[int, deque[float]] = defaultdict(deque)
_SENSITIVE_RESULT_TERMS = ("权限", "封禁", "风控", "安全", "隐私", "密钥", "token", "密码")
_OUTGOING_HOOK_BOUND = False
_SUPPRESS_OUTGOING_STICKER_FOLLOWUP: ContextVar[bool] = ContextVar("suppress_outgoing_sticker_followup", default=False)


@contextmanager
def suppress_outgoing_sticker_followup():
    token = _SUPPRESS_OUTGOING_STICKER_FOLLOWUP.set(True)
    try:
        yield
    finally:
        _SUPPRESS_OUTGOING_STICKER_FOLLOWUP.reset(token)


def outgoing_sticker_followup_suppressed() -> bool:
    return _SUPPRESS_OUTGOING_STICKER_FOLLOWUP.get()


def should_handle_outgoing_sticker_followup(exception: Exception | None, api: str) -> bool:
    return exception is None and api == "send_group_msg" and not outgoing_sticker_followup_suppressed()


def should_send_repeater_image(group_id: int, image_key: str, *, cooldown_sec: int, now: float | None = None) -> bool:
    key = str(image_key or "").strip()
    if not key:
        return False
    current = time.monotonic() if now is None else float(now)
    if current - _LAST_REPEATER_IMAGE_SENT_AT.get(int(group_id), float("-inf")) < max(0, int(cooldown_sec)):
        return False
    return key not in _RECENT_REPEATER_IMAGES[int(group_id)]


def should_schedule_outgoing_sticker(
    group_id: int,
    text: str,
    *,
    cooldown_sec: int,
    max_per_hour: int,
    now: float | None = None,
) -> bool:
    plain = str(text or "").strip()
    if not plain or any(term in plain.lower() for term in _SENSITIVE_RESULT_TERMS):
        return False
    current = time.monotonic() if now is None else float(now)
    group = int(group_id)
    scheduled = _STICKER_FOLLOWUP_SCHEDULED_AT[group]
    while scheduled and current - scheduled[0] >= 3600:
        scheduled.popleft()
    if max(0, int(max_per_hour)) <= len(scheduled):
        return False
    if scheduled and current - scheduled[-1] < max(0, int(cooldown_sec)):
        return False
    scheduled.append(current)
    return True


def note_repeater_image_sent(group_id: int, image_key: str, *, now: float | None = None) -> None:
    key = str(image_key or "").strip()
    if not key:
        return
    _LAST_REPEATER_IMAGE_SENT_AT[int(group_id)] = time.monotonic() if now is None else float(now)
    _RECENT_REPEATER_IMAGES[int(group_id)].append(key)


def reset_repeater_image_followup_state_for_tests() -> None:
    _LAST_REPEATER_IMAGE_SENT_AT.clear()
    _RECENT_REPEATER_IMAGES.clear()
    _STICKER_FOLLOWUP_SCHEDULED_AT.clear()


def bind_outgoing_sticker_followup() -> None:
    """在群文本成功发送后异步补一张 Repeater 表情图。"""
    global _OUTGOING_HOOK_BOUND
    if _OUTGOING_HOOK_BOUND:
        return
    _OUTGOING_HOOK_BOUND = True
    from nonebot.adapters import Bot as BaseBot

    @BaseBot.on_called_api
    async def schedule_outgoing_sticker(
        bot: BaseBot,
        exception: Exception | None,
        api: str,
        data: dict[str, Any],
        result: Any,
    ) -> None:
        if not should_handle_outgoing_sticker_followup(exception, api):
            return
        group_id = int(data.get("group_id") or 0)
        message = str(data.get("message") or "")
        if not group_id or "[CQ:image," in message:
            return
        from pallas.product.llm.config import get_llm_config

        cfg = get_llm_config()
        if not bool(cfg.llm_chat_sticker_enabled) or not should_schedule_outgoing_sticker(
            group_id,
            message,
            cooldown_sec=int(cfg.llm_chat_sticker_cooldown_sec),
            max_per_hour=int(getattr(cfg, "llm_chat_sticker_max_per_hour", 8)),
        ):
            return
        asyncio.create_task(
            send_outgoing_sticker_followup(bot, group_id, message, cooldown_sec=int(cfg.llm_chat_sticker_cooldown_sec)),
            name=f"outgoing_sticker_{bot.self_id}_{group_id}",
        )


async def send_outgoing_sticker_followup(bot: Any, group_id: int, text: str, *, cooldown_sec: int) -> None:
    await asyncio.sleep(0.7)
    from pallas.product.llm.delivery import send_repeater_emotion_image

    await send_repeater_emotion_image(bot, group_id, int(bot.self_id), 0, text, cooldown_sec=cooldown_sec)
