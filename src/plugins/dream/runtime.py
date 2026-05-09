from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.exception import ActionFailed

from src.common.config import BotConfig
from src.common.db import Message as MessageModel
from src.common.db import make_message_repository
from src.plugins.pallas_image.draw_archive import random_archived_png_bytes

from .dream_labels import pick_pseudo_sender_at
from .echo_sample import random_echo_nickname, sample_learned_echo_line
from .history_bottle import dream_keywords_for_insert, sample_historical_drift

if TYPE_CHECKING:
    from .payload import DriftPayload

message_repo = make_message_repository()

_MAX_QUEUE = 800
_dream_lock = asyncio.Lock()
_dream_active: set[tuple[int, int]] = set()
_dream_tasks: dict[tuple[int, int], asyncio.Task] = {}
_drift_queues: dict[tuple[int, int], asyncio.Queue[DriftPayload]] = {}


def get_drift_queue(key: tuple[int, int]) -> asyncio.Queue[DriftPayload]:
    if key not in _drift_queues:
        _drift_queues[key] = asyncio.Queue(maxsize=_MAX_QUEUE)
    return _drift_queues[key]


async def stop_dream_worker(bot_id: int, group_id: int) -> None:
    key = (bot_id, group_id)
    t = _dream_tasks.pop(key, None)
    if t and not t.done():
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    async with _dream_lock:
        _dream_active.discard(key)
    q = _drift_queues.pop(key, None)
    if q is not None:
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break


async def broadcast_drift(bot_id: int, source_group_id: int, payload: DriftPayload) -> None:
    """联机梦：仅向「当前也在做梦的其它群」投递；多群时每条随机抽一个接收群（两群时自然一对一互传）。"""
    async with _dream_lock:
        targets = [gid for bid, gid in _dream_active if bid == bot_id and gid != source_group_id]
    if not targets:
        return
    gid = random.choice(targets)
    key = (bot_id, gid)
    q = get_drift_queue(key)
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        q.put_nowait(payload)
    except asyncio.QueueFull:
        pass


async def launch_dream_worker(bot_id: int, group_id: int, duration_sec: int) -> None:
    key = (bot_id, group_id)
    await stop_dream_worker(bot_id, group_id)
    cfg = BotConfig(bot_id, group_id)
    await cfg.start_dream(duration_sec)
    async with _dream_lock:
        _dream_active.add(key)
    _dream_tasks[key] = asyncio.create_task(_dream_worker_loop(bot_id, group_id))


async def _dream_worker_loop(bot_id: int, group_id: int) -> None:
    key = (bot_id, group_id)
    cfg = BotConfig(bot_id, group_id)
    sent_images = 0
    q = get_drift_queue(key)
    try:
        while await cfg.is_dreaming():
            await asyncio.sleep(random.uniform(0.0, 15.0))
            if not await cfg.is_dreaming():
                break
            try:
                bot = get_bot(str(bot_id))
            except Exception as e:
                logger.debug("dream worker get_bot failed: {}", e)
                continue
            item: DriftPayload | None = None
            try:
                item = q.get_nowait()
            except asyncio.QueueEmpty:
                item = None
            try:
                # 联机漂流优先：有队列则先发他群传来的内容，再走图或学到的句子
                if item and item.image_bytes and sent_images < 3:
                    await _send_group_drift_image(bot, group_id, item.nickname, item.image_bytes)
                    sent_images += 1
                elif item and item.text:
                    await _send_group_drift_text(bot, group_id, item.nickname, item.text)
                else:
                    hist = await sample_historical_drift(bot_id=bot_id, exclude_group_id=group_id)
                    if hist is None:
                        hist = await sample_historical_drift(bot_id=bot_id, exclude_group_id=None)
                    if hist and hist.image_bytes and sent_images < 3:
                        await _send_group_drift_image(bot, group_id, hist.nickname, hist.image_bytes)
                        sent_images += 1
                        continue
                    if hist and hist.text:
                        await _send_group_drift_text(bot, group_id, hist.nickname, hist.text)
                        continue
                    if sent_images < 3 and random.random() < 0.38:
                        data = await random_archived_png_bytes()
                        if data:
                            await _send_group_archived_draw_image(bot, group_id, data)
                            sent_images += 1
                            continue
                    line = await sample_learned_echo_line()
                    if line:
                        await _send_group_drift_text(bot, group_id, random_echo_nickname(), line)
            except ActionFailed as e:
                logger.debug("dream send failed: {}", e)
            except Exception as e:
                logger.warning("dream worker tick error: {}", e)
    finally:
        async with _dream_lock:
            _dream_active.discard(key)
        _dream_tasks.pop(key, None)


def drift_at_nickname(nickname: str) -> str:
    n = (nickname or "").strip() or "某位博士"
    return n if n.startswith("@") else f"@{n}"


async def _send_group_drift_text(bot: Bot, group_id: int, nickname: str, text: str) -> None:
    body = f"{drift_at_nickname(nickname)}：{text}"
    await bot.send_group_msg(group_id=group_id, message=Message(MessageSegment.text(body)))


async def _send_group_drift_image(bot: Bot, group_id: int, nickname: str, data: bytes) -> None:
    """跨群漂流图"""
    head = f"{drift_at_nickname(nickname)}："
    await bot.send_group_msg(
        group_id=group_id,
        message=MessageSegment.text(head) + MessageSegment.image(data),
    )


async def _send_group_archived_draw_image(bot: Bot, group_id: int, data: bytes) -> None:
    """本地归档的牛牛画画图"""
    head = pick_pseudo_sender_at() + "："
    await bot.send_group_msg(
        group_id=group_id,
        message=MessageSegment.text(head) + MessageSegment.image(data),
    )


async def log_dream_chat_to_db(event: GroupMessageEvent) -> None:
    plain = event.get_plaintext().strip()
    if not plain:
        plain = " "
    is_plain = "[CQ:" not in event.raw_message
    nick = (event.sender.card or event.sender.nickname or str(event.user_id)).strip() or str(event.user_id)
    m = MessageModel.model_construct(
        group_id=event.group_id,
        user_id=event.user_id,
        bot_id=event.self_id,
        raw_message=event.raw_message,
        is_plain_text=is_plain,
        plain_text=plain[:4000],
        keywords=dream_keywords_for_insert(nick),
        time=int(getattr(event, "time", None) or time.time()),
    )
    try:
        await message_repo.bulk_insert([m])
    except Exception as e:
        logger.debug("dream message db insert failed: {}", e)
