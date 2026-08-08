"""Repeater 文本后的随机缓存表情图。"""

from __future__ import annotations

import random
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageSegment

from pallas.core.shared.utils.media_cache import get_recent_images
from pallas.product.llm.sticker_followup import (
    note_repeater_image_sent,
    should_schedule_outgoing_sticker,
    should_send_repeater_image,
)

from .config import get_repeater_config


async def maybe_send_repeater_sticker_followup(
    bot: Any,
    group_id: int,
    message: str,
    *,
    cfg: Any | None = None,
) -> bool:
    text = str(message or "")
    config = cfg or get_repeater_config()
    if "[CQ:" in text or random.random() >= float(config.sticker_followup_rate):
        return False
    if not should_schedule_outgoing_sticker(
        group_id,
        text,
        cooldown_sec=int(config.sticker_followup_cooldown_sec),
        max_per_hour=int(config.sticker_followup_max_per_hour),
    ):
        return False
    try:
        candidates = await get_recent_images(8)
    except Exception as exc:
        logger.info("repeater sticker followup cache lookup skipped group={}: {}", group_id, exc)
        return False
    if not candidates:
        return False
    image_key, image = random.choice(candidates)
    if not should_send_repeater_image(group_id, image_key, cooldown_sec=int(config.sticker_followup_cooldown_sec)):
        return False
    from pallas.product.llm.delivery import prepare_sticker_image

    try:
        await bot.call_api(
            "send_group_msg",
            message=MessageSegment.image(file=prepare_sticker_image(image)),
            group_id=int(group_id),
        )
    except Exception:
        return False
    note_repeater_image_sent(group_id, image_key)
    return True
