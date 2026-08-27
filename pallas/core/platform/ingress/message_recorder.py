"""群消息旁路记录器：无条件把每条群消息落库到 message 表。

初衷是让 chat.history / chat.recent_summary 这类「最近聊了什么」工具拿到完整的群消息，
而不是只依赖 repeater 抢占链路（claim 失败、被 scrub、self 消息、fleet 消息、队列满、
worker 停机等场景都会漏记）。

本模块在事件入口最早处捕获 (GroupMessageEvent)，走独立的有界队列 + 后台 writer 批量落库，
不阻塞消息处理主循环，也不参与任何 discard 决策。message 表已对
(group_id, bot_id, message_id) 建唯一约束并幂等写入，重复捕获不会产生重复行。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from nonebot.log import logger

from pallas.core.foundation.db import Message, make_message_repository
from pallas.core.shared.reply_command_rule import extract_reply_id_from_raw_message

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

_QUEUE_MAX = 4096
_FLUSH_BATCH_SIZE = 256
_SHUTDOWN_DRAIN_TIMEOUT = 2.0


def build_message(event: GroupMessageEvent, bot: Bot) -> Message:
    """从群消息事件构造 message 表记录（字段对齐 Message 模型）。"""
    sender = getattr(event, "sender", None)
    sender_name = getattr(sender, "card", "") or getattr(sender, "nickname", "") or ""
    raw_message = str(getattr(event, "raw_message", "") or "")
    plain_text = str(event.get_plaintext() or "")
    return Message.model_construct(
        group_id=int(getattr(event, "group_id", 0) or 0),
        user_id=int(getattr(event, "user_id", 0) or 0),
        bot_id=int(getattr(bot, "self_id", 0) or 0),
        raw_message=raw_message,
        is_plain_text="[CQ:" not in raw_message and bool(plain_text),
        plain_text=plain_text,
        keywords="",
        sender_name=sender_name,
        message_id=int(getattr(event, "message_id", 0) or 0) or None,
        reply_to_message_id=extract_reply_id_from_raw_message(raw_message),
        suppressed_by_rage=False,
        time=int(getattr(event, "time", 0) or 0),
    )


class MessageRecorder:
    """有界队列 + 后台批量落库的旁路记录器。"""

    def __init__(self, *, queue_max: int = _QUEUE_MAX, batch_size: int = _FLUSH_BATCH_SIZE) -> None:
        self._queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=queue_max)
        self._batch_size = batch_size
        self._repo = make_message_repository()
        self._writer: asyncio.Task[None] | None = None
        self._enabled = True

    def capture(self, event: Event, bot: Bot) -> None:
        if not self._enabled:
            return
        from nonebot.adapters.onebot.v11 import GroupMessageEvent

        if not isinstance(event, GroupMessageEvent):
            return
        try:
            message = build_message(event, bot)
        except Exception:
            logger.exception("message_recorder build message failed")
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("message_recorder queue full, dropping message")

    async def start(self) -> None:
        if self._writer is not None and not self._writer.done():
            return
        self._writer = asyncio.create_task(self._run_writer(), name="message_recorder_writer")
        logger.debug("message_recorder writer started")

    async def stop(self) -> None:
        self._enabled = False
        if self._writer is None or self._writer.done():
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=_SHUTDOWN_DRAIN_TIMEOUT)
        except TimeoutError:
            pass
        self._writer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._writer
        self._writer = None

    async def _run_writer(self) -> None:
        while True:
            batch: list[Message] = []
            try:
                first = await self._queue.get()
            except asyncio.CancelledError:
                return
            batch.append(first)
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await self._repo.bulk_insert(batch)
            except Exception as exc:
                logger.error("message_recorder bulk_insert failed for [{}] messages: [{}]", len(batch), exc)
            finally:
                for _ in batch:
                    self._queue.task_done()


_recorder: MessageRecorder | None = None


def message_recorder() -> MessageRecorder:
    global _recorder
    if _recorder is None:
        _recorder = MessageRecorder()
    return _recorder


def capture_group_message(event: Event, bot: Bot) -> None:
    """事件入口最早处调用；非群消息或被禁用时静默跳过。"""
    message_recorder().capture(event, bot)


def bind_message_recorder_lifecycle() -> None:
    from nonebot import get_driver

    driver = get_driver()

    @driver.on_startup
    async def _on_startup():
        await message_recorder().start()

    @driver.on_shutdown
    async def _on_shutdown():
        await message_recorder().stop()
