"""LLM 回复后的图片跟随判定。"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.structured_reply import parse_structured_reply

_LAST_REPEATER_IMAGE_SENT_AT: dict[int, float] = {}
_RECENT_REPEATER_IMAGES: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=8))


def should_attach_repeater_image(task: dict[str, Any], reply_text: str, raw_reply: str) -> bool:
    """只在模型明确选择图片时追加一张 Repeater 已学习的图片。"""
    if str(task.get("task_type") or "").strip() != LLM_CHAT_TASK_TYPE:
        return False
    if not str(reply_text or "").strip():
        return False
    return parse_structured_reply(raw_reply).sticker == "send"


def should_send_repeater_image(group_id: int, image_key: str, *, cooldown_sec: int, now: float | None = None) -> bool:
    key = str(image_key or "").strip()
    if not key:
        return False
    current = time.monotonic() if now is None else float(now)
    if current - _LAST_REPEATER_IMAGE_SENT_AT.get(int(group_id), float("-inf")) < max(0, int(cooldown_sec)):
        return False
    return key not in _RECENT_REPEATER_IMAGES[int(group_id)]


def note_repeater_image_sent(group_id: int, image_key: str, *, now: float | None = None) -> None:
    key = str(image_key or "").strip()
    if not key:
        return
    _LAST_REPEATER_IMAGE_SENT_AT[int(group_id)] = time.monotonic() if now is None else float(now)
    _RECENT_REPEATER_IMAGES[int(group_id)].append(key)


def reset_repeater_image_followup_state_for_tests() -> None:
    _LAST_REPEATER_IMAGE_SENT_AT.clear()
    _RECENT_REPEATER_IMAGES.clear()
