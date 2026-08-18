"""AI 回调结果投递到 QQ 群。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import NetworkError
from nonebot.exception import ActionFailed

_CALLBACK_SEND_ERRORS = (ActionFailed, NetworkError)


@dataclass(frozen=True)
class DeliveryReceipt:
    delivered: bool
    message_id: int | None = None


def parse_delivery_message_id(value: object) -> int | None:
    candidate = value.get("message_id") if isinstance(value, Mapping) else getattr(value, "message_id", None)
    if candidate is None:
        data = value.get("data") if isinstance(value, Mapping) else getattr(value, "data", None)
        candidate = data.get("message_id") if isinstance(data, Mapping) else getattr(data, "message_id", None)
    try:
        parsed = int(candidate)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def build_group_text_message(
    text: str,
    *,
    reply_to_message_id: int | None = None,
    at_user_id: int | None = None,
) -> str | Message:
    if reply_to_message_id:
        return MessageSegment.reply(reply_to_message_id) + text
    if at_user_id:
        return MessageSegment.at(at_user_id) + text
    return text


async def send_group_message(
    bot,
    group_id: int,
    message: str,
    *,
    reply_to_message_id: int | None = None,
    at_user_id: int | None = None,
) -> bool:
    receipt = await send_group_message_with_receipt(
        bot,
        group_id,
        message,
        reply_to_message_id=reply_to_message_id,
        at_user_id=at_user_id,
    )
    return receipt.delivered


async def send_group_message_with_receipt(
    bot,
    group_id: int,
    message: str,
    *,
    reply_to_message_id: int | None = None,
    at_user_id: int | None = None,
) -> DeliveryReceipt:
    outgoing = build_group_text_message(
        message,
        reply_to_message_id=reply_to_message_id,
        at_user_id=at_user_id,
    )
    logger.debug(
        f"Bot [{getattr(bot, 'self_id', '<unknown>')}] sending a message to group [{group_id}], "
        f"length [{len(message or '')}]"
    )
    try:
        result = await bot.call_api(
            "send_group_msg",
            **{
                "message": outgoing,
                "group_id": group_id,
            },
        )
        logger.debug(
            f"Bot [{getattr(bot, 'self_id', '<unknown>')}] sent a message to group [{group_id}], "
            f"length [{len(message or '')}]"
        )
        return DeliveryReceipt(
            delivered=True,
            message_id=parse_delivery_message_id(result),
        )
    except _CALLBACK_SEND_ERRORS as e:
        logger.warning("AI callback failed to send group message to group [{}]: [{}].", group_id, e)
        return DeliveryReceipt(delivered=False)


async def send_group_image(bot, group_id: int, image_bytes: bytes, *, at_user_id: int | None = None) -> bool:
    from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

    image_api = import_plugin_submodule("draw", "image_api")
    if not image_bytes:
        return False
    if not image_api.is_valid_generated_image(image_bytes):
        logger.warning(
            "AI callback rejected image for group [{}] with length [{}].",
            group_id,
            len(image_bytes),
        )
        return False
    message = image_api.optional_message_at_user(at_user_id, MessageSegment.image(image_bytes))
    logger.debug(
        "AI callback is sending an image for unknown task from bot [{}] to group [{}], bytes [{}], at user [{}].",
        getattr(bot, "self_id", "<unknown>"),
        group_id,
        len(image_bytes),
        at_user_id,
    )
    try:
        await bot.call_api(
            "send_group_msg",
            **{
                "message": message,
                "group_id": group_id,
            },
        )
        logger.debug(
            "AI callback sent an image for unknown task from bot [{}] to group [{}], bytes [{}], at user [{}].",
            getattr(bot, "self_id", "<unknown>"),
            group_id,
            len(image_bytes),
            at_user_id,
        )
        return True
    except _CALLBACK_SEND_ERRORS as e:
        logger.warning("AI callback failed to send group image to group [{}]: [{}].", group_id, e)
        return False


async def send_group_voice(bot, group_id: int, audio_bytes: bytes) -> bool:
    if not audio_bytes:
        return False
    logger.debug(
        "AI callback is sending voice for unknown task from bot [{}] to group [{}], bytes [{}].",
        getattr(bot, "self_id", "<unknown>"),
        group_id,
        len(audio_bytes),
    )
    try:
        await bot.call_api(
            "send_group_msg",
            **{
                "message": MessageSegment.record(file=audio_bytes),
                "group_id": group_id,
            },
        )
        logger.debug(
            "AI callback sent voice for unknown task from bot [{}] to group [{}], bytes [{}].",
            getattr(bot, "self_id", "<unknown>"),
            group_id,
            len(audio_bytes),
        )
        return True
    except _CALLBACK_SEND_ERRORS as e:
        logger.warning("AI callback failed to send voice to group [{}]: [{}].", group_id, e)
        return False
