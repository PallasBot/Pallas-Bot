"""work aux 的复读学习处理器。"""

from __future__ import annotations

from typing import Any

from .learner import Learner
from .work_payload import RepeaterLearnPayload


async def handle_repeater_learn(payload: dict[str, Any]) -> None:
    await Learner.process_work_payload(RepeaterLearnPayload.from_dict(payload))
    from pallas.core.platform.ingress.hotpath_metrics import record_learn_completed

    record_learn_completed()


def repeater_work_handlers():
    from pallas.core.shared.utils.media_cache import handle_image_cache_capture
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
        "repeater.semantic_style": handle_repeater_semantic_style,
        "repeater.semantic_style.backfill": handle_repeater_semantic_style_backfill,
        "repeater.semantic_style.backfill.scan": handle_repeater_semantic_style_backfill_scan,
        "repeater.semantic_style.visual": handle_repeater_semantic_style_visual,
        "image_cache.capture": handle_image_cache_capture,
        "sticker_vision.select": handle_sticker_vision_select,
        "sticker.label.visual": handle_sticker_label_visual,
    }
