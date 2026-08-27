"""work aux 的复读学习处理器。"""

from __future__ import annotations

from typing import Any

from .learner import Learner
from .work_payload import RepeaterLearnPayload


async def handle_repeater_learn(payload: dict[str, Any]) -> None:
    await Learner.process_work_payload(RepeaterLearnPayload.from_dict(payload))
    from pallas.core.platform.ingress.hotpath_metrics import record_learn_completed

    record_learn_completed()


async def handle_repeater_message(payload: dict[str, Any]) -> None:
    from .message_store import MessageStore
    from .model import ChatData

    raw_message = payload.get("message")
    if not isinstance(raw_message, dict):
        return
    chat_data = ChatData(
        group_id=int(raw_message.get("group_id") or 0),
        user_id=int(raw_message.get("user_id") or 0),
        bot_id=int(raw_message.get("bot_id") or 0),
        raw_message=str(raw_message.get("raw_message") or ""),
        plain_text=str(raw_message.get("plain_text") or ""),
        sender_name=str(raw_message.get("sender_name") or ""),
        message_id=raw_message.get("message_id"),
        reply_to_message_id=raw_message.get("reply_to_message_id"),
        suppressed_by_rage=bool(raw_message.get("suppressed_by_rage", False)),
        time=int(raw_message.get("time") or 0),
    )
    await MessageStore.persist_message(chat_data)


def repeater_work_handlers():
    from pallas.core.shared.utils.media_cache import handle_image_cache_capture
    from pallas.product.llm.group_insight_processor import handle_group_insight
    from pallas.product.llm.repeater_semantic_style import (
        handle_repeater_semantic_style,
        handle_repeater_semantic_style_backfill,
        handle_repeater_semantic_style_backfill_scan,
        handle_repeater_semantic_style_visual,
    )
    from pallas.product.llm.sticker_label_jobs import handle_sticker_label_visual
    from pallas.product.llm.sticker_vision import handle_sticker_vision_select

    return {
        "repeater.learn": handle_repeater_learn,
        "repeater.message": handle_repeater_message,
        "group.insight": handle_group_insight,
        "repeater.semantic_style": handle_repeater_semantic_style,
        "repeater.semantic_style.backfill": handle_repeater_semantic_style_backfill,
        "repeater.semantic_style.backfill.scan": handle_repeater_semantic_style_backfill_scan,
        "repeater.semantic_style.visual": handle_repeater_semantic_style_visual,
        "image_cache.capture": handle_image_cache_capture,
        "sticker_vision.select": handle_sticker_vision_select,
        "sticker.label.visual": handle_sticker_label_visual,
    }
