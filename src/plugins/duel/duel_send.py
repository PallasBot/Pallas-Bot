from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Literal

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.exception import ActionFailed
from nonebot.matcher import Matcher  # noqa: TC002

from src.plugins.duel.duel_session import register_duel_narrative_line

Speaker = Literal["neutral", "challenger", "defender"]


@dataclass
class RoundLineBuffer:
    """本幕剧目片段缓冲，幕末与双方数值简报合并发送。"""

    parts: list[str] = field(default_factory=list)
    send_kwargs: dict[str, Any] = field(default_factory=dict)


_round_buffer: ContextVar[RoundLineBuffer | None] = ContextVar("_round_buffer", default=None)


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


def round_buffer_prepend(text: str) -> None:
    """将文本接到本幕缓冲首部（用于幕标与首段剧目合一）。"""
    buf = _round_buffer.get()
    if buf is None:
        return
    chunk = text.strip()
    if not chunk:
        return
    if buf.parts:
        buf.parts[0] = f"{chunk}\n{buf.parts[0]}"
    else:
        buf.parts.append(chunk)


def take_round_buffer_body() -> str:
    """取出并清空本幕缓冲正文（不含 send_kwargs）。"""
    buf = _round_buffer.get()
    if buf is None or not buf.parts:
        return ""
    body = "\n\n".join(buf.parts)
    buf.parts.clear()
    return body


async def send_duel_line_merge_buffer(
    group_id: int,
    text: str,
    *,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    image_url: str | None = None,
) -> None:
    """将缓冲剧目与 text 合并为一条即时消息（紧凑幕 QTE 提示用）。"""
    prefix = take_round_buffer_body()
    chunk = text.strip()
    if prefix and chunk:
        body = f"{prefix}\n\n{chunk}"
    else:
        body = prefix or chunk
    if not body and not image_url:
        return
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
    await deliver_duel_line(body, image_url=image_url, **kwargs)


async def release_round_line_buffer() -> None:
    """发出本幕已缓冲的剧目（不含幕末数值行），便于紧接 QTE 提示或即时反馈。"""
    buf = _round_buffer.get()
    if buf is None or not buf.parts or not buffer_can_deliver(buf):
        return
    body = "\n\n".join(buf.parts)
    await deliver_duel_line(body, **buf.send_kwargs)
    buf.parts.clear()


async def flush_round_line_buffer(suffix: str) -> None:
    """将本幕已缓冲的剧目片段与幕末结算（suffix）合并发出。"""
    buf = _round_buffer.get()
    if buf is None or not buffer_can_deliver(buf):
        return
    if not buf.parts and not suffix.strip():
        return
    body = "\n\n".join(buf.parts)
    if suffix.strip():
        body = f"{body}\n\n{suffix.strip()}" if body else suffix.strip()
    await deliver_duel_line(body, **buf.send_kwargs)
    buf.parts.clear()


async def send_duel_line(
    group_id: int,
    text: str,
    *,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    immediate: bool = False,
    image_url: str | None = None,
) -> None:
    """发送剧目。默认写入本幕缓冲（多事件累加）；immediate 时立即发群（QTE 提示等）。"""
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
    chunk = text.strip()
    if not chunk and not image_url:
        return
    buf = _round_buffer.get()
    if buf is not None and not immediate and not image_url:
        if chunk:
            buf.parts.append(chunk)
        buf.send_kwargs = kwargs
        return
    await deliver_duel_line(chunk, image_url=image_url, **kwargs)


def build_duel_outbound_message(text: str, *, image_url: str | None = None) -> Message:
    """剧目正文与可选头像合并为一条群消息。"""
    chunk = text.strip()
    msg = Message(chunk) if chunk else Message()
    if image_url:
        msg = msg + Message(MessageSegment.image(file=image_url))
    return msg


async def deliver_duel_line(
    text: str,
    *,
    group_id: int,
    matcher: Matcher,
    challenger_id: str,
    defender_id: str,
    bot_mode: bool,
    speaker: Speaker = "neutral",
    challenger_is_bot: bool = False,
    defender_is_bot: bool = False,
    image_url: str | None = None,
) -> None:
    """实际发群并登记复读忽略。"""
    chunk = text.strip()
    if chunk:
        await register_duel_narrative_line(group_id, chunk)
    outbound = build_duel_outbound_message(chunk, image_url=image_url)
    route_bot = bot_mode
    if not route_bot and speaker == "challenger" and challenger_is_bot:
        route_bot = True
    if not route_bot and speaker == "defender" and defender_is_bot:
        route_bot = True
    if not route_bot:
        await matcher.send(outbound)
        return
    qq = _speaker_qq(speaker, challenger_id, defender_id, matcher)
    bots = get_bots()
    inst = bots.get(str(qq))
    if inst is None:
        inst = matcher.bot
    try:
        await inst.send_group_msg(group_id=group_id, message=outbound)
    except ActionFailed as err:
        logger.warning(f"duel send failed group={group_id} qq={qq}: {err}")
        await matcher.send(outbound)


def _speaker_qq(
    speaker: Speaker,
    challenger_id: str,
    defender_id: str,
    matcher: Matcher,
) -> str:
    if speaker == "challenger":
        return challenger_id
    if speaker == "defender":
        return defender_id
    return str(matcher.bot.self_id)
