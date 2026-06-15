from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Literal

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed, ApiNotAvailable, NetworkError
from nonebot.matcher import Matcher  # noqa: TC002

from src.platform.bot_runtime.send_unavailable import is_bot_send_unavailable, log_bot_send_unavailable
from src.plugins.duel.duel_message import (
    append_duel_message,
    coerce_duel_message,
    duel_join_blocks,
    message_has_content,
)
from src.plugins.duel.duel_session import register_duel_narrative_line

_SEND_ERRORS = (ActionFailed, NetworkError, ApiNotAvailable, asyncio.CancelledError)


def log_duel_send_error(err: BaseException, *, group_id: int, detail: str) -> None:
    if is_bot_send_unavailable(err):
        log_bot_send_unavailable(err, context="duel", group=group_id)
    else:
        logger.warning(detail)


Speaker = Literal["neutral", "challenger", "defender"]


@dataclass
class RoundLineBuffer:
    """本幕剧目片段缓冲，幕末与双方数值简报合并发送。"""

    parts: list[Message] = field(default_factory=list)
    send_kwargs: dict[str, Any] = field(default_factory=dict)


_round_buffer: ContextVar[RoundLineBuffer | None] = ContextVar("_round_buffer", default=None)
_routing_bot: ContextVar[Any] = ContextVar("_duel_routing_bot", default=None)


def bind_duel_routing_bot(bot: Any) -> Token:
    return _routing_bot.set(bot)


def reset_duel_routing_bot(token: Token) -> None:
    _routing_bot.reset(token)


def duel_routing_bot() -> Any:
    inst = _routing_bot.get()
    if inst is None:
        raise RuntimeError("duel routing bot 未绑定")
    return inst


def build_duel_deliver_kwargs(
    *,
    group_id: int,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
) -> dict[str, Any]:
    """本幕发群参数；幕缓冲开启时写入，避免仅即时/QTE 消息时 flush 缺参。"""
    return {
        "group_id": group_id,
        "matcher": matcher,
        "challenger_id": challenger_id,
        "defender_id": defender_id,
        "bot_mode": bot_mode,
        "speaker": speaker,
        "challenger_is_bot": challenger_is_bot,
        "defender_is_bot": defender_is_bot,
    }


def begin_round_line_buffer(**deliver_kwargs: Any) -> Token:
    buf = RoundLineBuffer()
    buf.send_kwargs = dict(deliver_kwargs)
    return _round_buffer.set(buf)


def reset_round_line_buffer(token: Token) -> None:
    _round_buffer.reset(token)


def buffer_can_deliver(buf: RoundLineBuffer) -> bool:
    required = ("group_id", "matcher", "challenger_id", "defender_id", "bot_mode")
    return all(k in buf.send_kwargs for k in required)


def round_buffer_prepend(chunk: str | Message) -> None:
    """将文本接到本幕缓冲首部。"""
    buf = _round_buffer.get()
    if buf is None:
        return
    msg = coerce_duel_message(chunk)
    if not message_has_content(msg):
        return
    if buf.parts:
        buf.parts[0] = append_duel_message(msg, buf.parts[0], sep="\n")
    else:
        buf.parts.append(msg)


def take_round_buffer_body() -> Message:
    """取出并清空本幕缓冲正文。"""
    buf = _round_buffer.get()
    if buf is None or not buf.parts:
        return Message()
    body = duel_join_blocks(buf.parts, sep="\n\n")
    buf.parts.clear()
    return body


async def send_duel_line_merge_buffer(
    group_id: int,
    text: str | Message,
    *,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    image_bytes: bytes | None = None,
    split_image_on_fail: bool = False,
) -> bool:
    """将缓冲剧目与 text 合并为一条即时消息。返回是否成功发群。"""
    prefix = take_round_buffer_body()
    chunk = coerce_duel_message(text)
    if message_has_content(prefix) and message_has_content(chunk):
        body = append_duel_message(prefix, chunk, sep="\n\n")
    else:
        body = chunk if message_has_content(chunk) else prefix
    if not message_has_content(body) and not image_bytes:
        return False
    kwargs = build_duel_deliver_kwargs(
        group_id=group_id,
        matcher=matcher,
        challenger_id=challenger_id,
        defender_id=defender_id,
        bot_mode=bot_mode,
        speaker=speaker,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
    )
    return await deliver_duel_line(
        body,
        image_bytes=image_bytes,
        split_image_on_fail=split_image_on_fail,
        **kwargs,
    )


async def release_round_line_buffer() -> None:
    """发出本幕已缓冲的剧目，便于紧接 QTE 提示或即时反馈。"""
    buf = _round_buffer.get()
    if buf is None or not buf.parts or not buffer_can_deliver(buf):
        return
    body = duel_join_blocks(buf.parts, sep="\n\n")
    await deliver_duel_line(body, **buf.send_kwargs)
    buf.parts.clear()


async def flush_round_line_buffer(suffix: str | Message) -> None:
    """将本幕已缓冲的剧目片段与幕末结算合并发出。"""
    buf = _round_buffer.get()
    if buf is None or not buffer_can_deliver(buf):
        return
    suffix_msg = coerce_duel_message(suffix)
    if not buf.parts and not message_has_content(suffix_msg):
        return
    body = duel_join_blocks(buf.parts, sep="\n\n")
    if message_has_content(suffix_msg):
        body = append_duel_message(body, suffix_msg, sep="\n\n") if message_has_content(body) else suffix_msg
    await deliver_duel_line(body, **buf.send_kwargs)
    buf.parts.clear()


async def send_duel_line(
    group_id: int,
    text: str | Message,
    *,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    immediate: bool = False,
    image_bytes: bytes | None = None,
    split_image_on_fail: bool = False,
) -> bool:
    """发送剧目。默认写入本幕缓冲；immediate 时立即发群。返回是否已发群或写入缓冲。"""
    kwargs = build_duel_deliver_kwargs(
        group_id=group_id,
        matcher=matcher,
        challenger_id=challenger_id,
        defender_id=defender_id,
        bot_mode=bot_mode,
        speaker=speaker,
        challenger_is_bot=challenger_is_bot,
        defender_is_bot=defender_is_bot,
    )
    chunk = coerce_duel_message(text)
    if not message_has_content(chunk) and not image_bytes:
        return False
    buf = _round_buffer.get()
    if buf is not None and not immediate and not image_bytes:
        if message_has_content(chunk):
            buf.parts.append(chunk)
        buf.send_kwargs = kwargs
        return True
    return await deliver_duel_line(
        chunk,
        image_bytes=image_bytes,
        split_image_on_fail=split_image_on_fail,
        **kwargs,
    )


def build_duel_outbound_message(body: Message, *, image_bytes: bytes | None = None) -> Message:
    """剧目正文与可选头像合并为一条群消息。"""
    msg = body if message_has_content(body) else Message()
    if image_bytes:
        msg = msg + Message(MessageSegment.image(image_bytes))
    return msg


async def _route_send_outbound(
    outbound: Message,
    *,
    group_id: int,
    matcher: Matcher,
    route_bot: bool,
    speaker: Speaker,
    challenger_id: str,
    defender_id: str,
    image_bytes: bytes | None = None,
) -> bool:
    if not message_has_content(outbound) and not image_bytes:
        return False
    if not route_bot:
        try:
            await matcher.send(outbound)
            return True
        except _SEND_ERRORS as err:
            log_duel_send_error(err, group_id=group_id, detail=f"duel matcher.send failed group={group_id}: {err}")
            return False
    qq = _speaker_qq(speaker, challenger_id, defender_id)
    bots = get_bots()
    inst = bots.get(str(qq))
    if inst is None:
        from src.platform.shard.coord.bot_action import send_group_message_as_bot
        from src.plugins.block import is_fleet_bot_qq

        try:
            qq_int = int(qq)
        except (TypeError, ValueError):
            qq_int = 0
        if is_fleet_bot_qq(qq_int):
            if await send_group_message_as_bot(
                qq_int,
                group_id,
                outbound,
                image_bytes=image_bytes,
            ):
                return True
        inst = duel_routing_bot()
    try:
        await inst.send_group_msg(group_id=group_id, message=outbound)
        return True
    except _SEND_ERRORS as err:
        log_duel_send_error(
            err, group_id=group_id, detail=f"duel send_group_msg failed group={group_id} qq={qq}: {err}"
        )
    try:
        await matcher.send(outbound)
        return True
    except _SEND_ERRORS as err:
        log_duel_send_error(err, group_id=group_id, detail=f"duel matcher.send fallback failed group={group_id}: {err}")
        return False


async def deliver_duel_line(
    text: str | Message,
    *,
    group_id: int,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    image_bytes: bytes | None = None,
    split_image_on_fail: bool = False,
) -> bool:
    """实际发群并登记复读忽略。乱入可拆成文本+图片两条，保证头像发出。"""
    chunk = coerce_duel_message(text)
    if not message_has_content(chunk) and not image_bytes:
        return False
    if message_has_content(chunk):
        await register_duel_narrative_line(group_id, chunk)
    route_bot = bot_mode
    if not route_bot and speaker == "challenger" and challenger_is_bot:
        route_bot = True
    if not route_bot and speaker == "defender" and defender_is_bot:
        route_bot = True
    send_kwargs = {
        "group_id": group_id,
        "matcher": matcher,
        "route_bot": route_bot,
        "speaker": speaker,
        "challenger_id": challenger_id,
        "defender_id": defender_id,
    }
    outbound = build_duel_outbound_message(chunk, image_bytes=image_bytes)
    send_kwargs["image_bytes"] = image_bytes
    if await _route_send_outbound(outbound, **send_kwargs):
        return True
    if image_bytes and split_image_on_fail:
        text_only = build_duel_outbound_message(chunk, image_bytes=None)
        img_only = build_duel_outbound_message(Message(), image_bytes=image_bytes)
        text_ok = message_has_content(text_only) and await _route_send_outbound(
            text_only, **{**send_kwargs, "image_bytes": None}
        )
        img_ok = await _route_send_outbound(img_only, **{**send_kwargs, "image_bytes": image_bytes})
        if img_ok and (text_ok or not message_has_content(chunk)):
            logger.info(f"duel send split text+image group={group_id}")
            return True
        logger.warning(f"duel intrusion image not sent group={group_id} text_ok={text_ok} img_ok={img_ok}")
        return False
    if image_bytes and message_has_content(chunk):
        text_only = build_duel_outbound_message(chunk, image_bytes=None)
        if await _route_send_outbound(text_only, **send_kwargs):
            logger.info(f"duel send text-only fallback group={group_id} (avatar skipped)")
            return True
    if not message_has_content(chunk):
        return False
    logger.warning(f"duel send dropped group={group_id}")
    return False


def _speaker_qq(
    speaker: Speaker,
    challenger_id: str,
    defender_id: str,
) -> str:
    if speaker == "challenger":
        return challenger_id
    if speaker == "defender":
        return defender_id
    return str(duel_routing_bot().self_id)
