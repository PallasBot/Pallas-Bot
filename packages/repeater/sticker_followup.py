"""Repeater 文本后的随机缓存表情图。"""

from __future__ import annotations

import random
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageSegment

from pallas.core.shared.utils.media_cache import get_recent_images
from pallas.product.llm.sticker_followup import (
    note_repeater_image_sent,
    recent_repeater_image_hashes,
    should_schedule_outgoing_sticker,
    should_send_repeater_image,
)

from .config import get_repeater_config


def derive_repeater_sticker_intent(message: str) -> str:
    """将复读文本归一为有限的表情意图，不能把原文交给选择器。"""
    text = str(message or "")
    if any(token in text for token in ("笑死", "哈哈", "好耶", "开心")):
        return "emotion:开心 action:大笑" if any(token in text for token in ("笑", "哈")) else "emotion:开心"
    if any(token in text for token in ("委屈", "呜呜")):
        return "emotion:委屈"
    if any(token in text for token in ("难过", "哭")):
        return "emotion:难过 action:哭" if "哭" in text else "emotion:难过"
    if any(token in text for token in ("生气", "气死", "恼火")):
        return "emotion:生气"
    if any(token in text for token in ("震惊", "惊了", "卧槽")):
        return "emotion:惊讶"
    return ""


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
        logger.info("Repeater sticker follow-up cache lookup skipped for group [{}]: [{}]", group_id, exc)
        return False
    if not candidates:
        return False
    from pallas.product.llm.delivery import rank_cached_sticker_candidates
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource

    ranked, _labels = await rank_cached_sticker_candidates(
        derive_repeater_sticker_intent(text),
        candidates,
        recent_hashes=recent_repeater_image_hashes(group_id),
        source=StickerLabelSource.REPEATER_CANDIDATE,
    )
    if not ranked:
        return False
    image_key = ranked[0].candidate.cq_code
    image = next(image for key, image in candidates if key == image_key)
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
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    note_repeater_image_sent(group_id, image_key, content_hash=content_hash_for_bytes(image))
    return True
