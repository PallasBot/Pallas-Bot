"""LLM 回复后的图片跟随判定。"""

from __future__ import annotations

from typing import Any

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.structured_reply import parse_structured_reply


def should_attach_repeater_image(task: dict[str, Any], reply_text: str, raw_reply: str) -> bool:
    """只在模型明确选择图片时追加一张 Repeater 已学习的图片。"""
    if str(task.get("task_type") or "").strip() != LLM_CHAT_TASK_TYPE:
        return False
    if not str(reply_text or "").strip():
        return False
    return parse_structured_reply(raw_reply).sticker == "send"
