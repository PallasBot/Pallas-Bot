from __future__ import annotations

import asyncio
import hashlib
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
from .drunk_synergy import send_one_random_history_line, try_drunk_dream_take_name
from .echo_sample import random_echo_nickname, sample_learned_echo_line
from .history_bottle import dream_keywords_for_insert, sample_historical_drift

if TYPE_CHECKING:
    from .payload import DriftPayload

message_repo = make_message_repository()

_MAX_QUEUE = 800
_SLEEP_MIN_SEC = 20.0
_SLEEP_MAX_SEC = 45.0
_DRUNK_DREAM_FAST_SLEEP_MIN = 5.0
_DRUNK_DREAM_FAST_SLEEP_MAX = 20.0
_DEFAULT_IMAGE_CAP = 3
_DRUNK_DREAM_IMAGE_CAP = 5
_HIST_RESAMPLE_ATTEMPTS = 12
_ARCHIVE_RESAMPLE_ATTEMPTS = 6
_ECHO_RESAMPLE_ATTEMPTS = 10


def dream_text_dedupe_key(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def dream_image_dedupe_key(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    sent_text_keys: set[str] = set()
    sent_image_keys: set[str] = set()
    q = get_drift_queue(key)
    image_cap = _DEFAULT_IMAGE_CAP
    drunk_synergy_used = False
    try:
        while await cfg.is_dreaming():
            drunk_now = (await cfg.drunkenness()) > 0
            do_drunk_synergy = drunk_now and not drunk_synergy_used
            if drunk_now:
                await asyncio.sleep(random.uniform(_DRUNK_DREAM_FAST_SLEEP_MIN, _DRUNK_DREAM_FAST_SLEEP_MAX))
            else:
                await asyncio.sleep(random.uniform(_SLEEP_MIN_SEC, _SLEEP_MAX_SEC))
            if not await cfg.is_dreaming():
                break
            try:
                bot = get_bot(str(bot_id))
            except Exception as e:
                logger.debug("dream worker get_bot failed: {}", e)
                continue
            if do_drunk_synergy:
                drunk_synergy_used = True
                image_cap = _DRUNK_DREAM_IMAGE_CAP
                try:
                    taken = await try_drunk_dream_take_name(bot=bot, bot_id=bot_id, group_id=group_id, cfg=cfg)
                    if taken is not None:
                        victim_id, victim_display = taken
                        await send_one_random_history_line(
                            bot,
                            bot_id=bot_id,
                            group_id=group_id,
                            user_id=victim_id,
                            display_name=victim_display,
                        )
                except ActionFailed as e:
                    logger.debug("dream drunk synergy send failed: {}", e)
                except Exception as e:
                    logger.warning("dream drunk synergy error: {}", e)
                continue
            item: DriftPayload | None = None
            try:
                item = q.get_nowait()
            except asyncio.QueueEmpty:
                item = None
            try:
                sent_queue_text = False
                sent_queue_image = False
                # 联机漂流优先：有队列则先发他群传来的内容；与本场已发去重
                if item and item.image_bytes and sent_images < image_cap:
                    ik = dream_image_dedupe_key(item.image_bytes)
                    if ik not in sent_image_keys:
                        await _send_group_drift_image(bot, group_id, item.nickname, item.image_bytes)
                        sent_image_keys.add(ik)
                        sent_images += 1
                        sent_queue_image = True
                elif item and item.text:
                    tk = dream_text_dedupe_key(item.text)
                    if tk not in sent_text_keys:
                        await _send_group_drift_text(bot, group_id, item.nickname, item.text)
                        sent_text_keys.add(tk)
                        sent_queue_text = True

                if sent_queue_text or sent_queue_image:
                    continue

                sent_from_hist = False
                for _ in range(_HIST_RESAMPLE_ATTEMPTS):
                    hist = await sample_historical_drift(bot_id=bot_id, exclude_group_id=group_id)
                    if hist is None:
                        hist = await sample_historical_drift(bot_id=bot_id, exclude_group_id=None)
                    if hist is None:
                        break
                    if hist.image_bytes and sent_images < image_cap:
                        ik = dream_image_dedupe_key(hist.image_bytes)
                        if ik not in sent_image_keys:
                            await _send_group_drift_image(bot, group_id, hist.nickname, hist.image_bytes)
                            sent_image_keys.add(ik)
                            sent_images += 1
                            sent_from_hist = True
                            break
                    if hist.text:
                        tk = dream_text_dedupe_key(hist.text)
                        if tk not in sent_text_keys:
                            await _send_group_drift_text(bot, group_id, hist.nickname, hist.text)
                            sent_text_keys.add(tk)
                            sent_from_hist = True
                            break

                if sent_from_hist:
                    continue

                sent_archive = False
                if sent_images < image_cap and random.random() < 0.38:
                    for _ in range(_ARCHIVE_RESAMPLE_ATTEMPTS):
                        data = await random_archived_png_bytes()
                        if not data:
                            break
                        ik = dream_image_dedupe_key(data)
                        if ik not in sent_image_keys:
                            await _send_group_archived_draw_image(bot, group_id, data)
                            sent_image_keys.add(ik)
                            sent_images += 1
                            sent_archive = True
                            break

                if sent_archive:
                    continue

                for _ in range(_ECHO_RESAMPLE_ATTEMPTS):
                    line = await sample_learned_echo_line()
                    if not line:
                        break
                    tk = dream_text_dedupe_key(line)
                    if tk not in sent_text_keys:
                        await _send_group_drift_text(bot, group_id, random_echo_nickname(), line)
                        sent_text_keys.add(tk)
                        break
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
