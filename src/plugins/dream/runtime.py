from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.exception import ActionFailed

from src.foundation.config import BotConfig
from src.foundation.db import Message as MessageModel
from src.foundation.db import make_message_repository

from .config import plugin_config as dream_plugin_config
from .dedupe_keys import dream_image_dedupe_key, dream_text_dedupe_key
from .dream_labels import pick_pseudo_sender_at
from .drunk_synergy import send_one_random_history_line, try_drunk_dream_take_name
from .echo_sample import random_echo_nickname, sample_learned_echo_line
from .history_bottle import dream_keywords_for_insert, register_recent_drift_dedupe_key, sample_historical_drift

if TYPE_CHECKING:
    from .payload import DriftPayload

message_repo = make_message_repository()

_MAX_QUEUE = 800
_DRUNK_DREAM_FAST_SLEEP_MIN = 5.0
_DRUNK_DREAM_FAST_SLEEP_MAX = 20.0
_DEFAULT_IMAGE_CAP = 3
_DRUNK_DREAM_IMAGE_CAP = 5
_ARCHIVE_RESAMPLE_ATTEMPTS = 6
DREAM_WAKE_TEXT = "……梦醒了。"


_dream_lock = asyncio.Lock()
_dream_active: set[tuple[int, int]] = set()
_dream_tasks: dict[tuple[int, int], asyncio.Task] = {}
_drift_queues: dict[tuple[int, int], asyncio.Queue[DriftPayload]] = {}


def get_drift_queue(key: tuple[int, int]) -> asyncio.Queue[DriftPayload]:
    if key not in _drift_queues:
        _drift_queues[key] = asyncio.Queue(maxsize=_MAX_QUEUE)
    return _drift_queues[key]


def enqueue_drift_payload(key: tuple[int, int], payload: DriftPayload) -> None:
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


async def deliver_drift_payload(bot_id: int, group_id: int, payload: DriftPayload) -> bool:
    key = (bot_id, group_id)
    async with _dream_lock:
        if key not in _dream_active:
            return False
    enqueue_drift_payload(key, payload)
    return True


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
    from src.platform.ingress.dream_host_gate import DREAM_HOST_GATE_PLUGIN
    from src.platform.multi_bot.dedup import needs_group_host_bot_gate, release_group_owned_gate_sync
    from src.platform.shard.coord.dream_drift import schedule_unregister_dream_active

    schedule_unregister_dream_active(bot_id, group_id)
    if needs_group_host_bot_gate():
        release_group_owned_gate_sync(DREAM_HOST_GATE_PLUGIN, group_id)
    q = _drift_queues.pop(key, None)
    if q is not None:
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break


async def broadcast_drift(bot_id: int, source_group_id: int, payload: DriftPayload) -> None:
    """联机梦：仅向「当前也在做梦的其它群」投递；多群时每条随机抽一个接收群（两群时自然一对一互传）。"""
    from src.platform.shard.coord.dream_drift import (
        list_peer_dream_groups_sync,
        schedule_publish_dream_drift,
    )
    from src.platform.shard.registry.config import is_sharding_active

    async with _dream_lock:
        local_targets = [gid for bid, gid in _dream_active if bid == bot_id and gid != source_group_id]
    targets = set(local_targets)
    if is_sharding_active():
        remote_targets = await asyncio.to_thread(
            list_peer_dream_groups_sync,
            bot_id,
            exclude_group_id=source_group_id,
        )
        targets.update(remote_targets)
    if not targets:
        return
    gid = random.choice(sorted(targets))
    key = (bot_id, gid)
    async with _dream_lock:
        local_hit = key in _dream_active
    if local_hit:
        enqueue_drift_payload(key, payload)
        return
    schedule_publish_dream_drift(bot_id, source_group_id, gid, payload)


async def send_dream_wake_text(bot_id: int, group_id: int) -> None:
    try:
        bot = get_bot(str(bot_id))
    except Exception as e:
        logger.debug(f"bot [{bot_id}] dream wake send get_bot failed in group [{group_id}]: {e}")
        return
    try:
        await bot.send_group_msg(
            group_id=group_id,
            message=Message(MessageSegment.text(DREAM_WAKE_TEXT)),
        )
    except ActionFailed as e:
        logger.debug(f"bot [{bot_id}] dream wake send failed in group [{group_id}]: {e}")


async def launch_dream_worker(bot_id: int, group_id: int, duration_sec: int) -> None:
    key = (bot_id, group_id)
    await stop_dream_worker(bot_id, group_id)
    cfg = BotConfig(bot_id, group_id)
    await cfg.start_dream(duration_sec)
    until_ts = time.time() + max(1, int(duration_sec))
    from src.platform.ingress.dream_host_gate import DREAM_HOST_GATE_PLUGIN
    from src.platform.multi_bot.dedup import bind_group_owned_gate_sync, needs_group_host_bot_gate
    from src.platform.shard.coord.dream_drift import schedule_register_dream_active

    schedule_register_dream_active(bot_id, group_id, until_ts)
    if needs_group_host_bot_gate():
        bind_group_owned_gate_sync(DREAM_HOST_GATE_PLUGIN, group_id, bot_id, gate_sec=float(duration_sec))
    async with _dream_lock:
        _dream_active.add(key)
    q = get_drift_queue(key)
    sent_text_keys: set[str] = set()
    sent_image_keys: set[str] = set()
    sent_images = 0
    image_cap = _DEFAULT_IMAGE_CAP
    try:
        bot0 = get_bot(str(bot_id))
        if await cfg.is_dreaming():
            sent_images = await _dream_worker_content_tick_once(
                bot0,
                bot_id=bot_id,
                group_id=group_id,
                q=q,
                sent_text_keys=sent_text_keys,
                sent_image_keys=sent_image_keys,
                sent_images=sent_images,
                image_cap=image_cap,
            )
    except ActionFailed as e:
        logger.debug(f"bot [{bot_id}] dream send failed (immediate tick) in group [{group_id}]: {e}")
    except Exception as e:
        logger.warning(f"bot [{bot_id}] dream worker immediate tick error in group [{group_id}]: {e}")
    _dream_tasks[key] = asyncio.create_task(
        _dream_worker_loop(
            bot_id,
            group_id,
            sent_text_keys=sent_text_keys,
            sent_image_keys=sent_image_keys,
            sent_images=sent_images,
        )
    )


async def _dream_worker_content_tick_once(
    bot: Bot,
    *,
    bot_id: int,
    group_id: int,
    q: asyncio.Queue[DriftPayload],
    sent_text_keys: set[str],
    sent_image_keys: set[str],
    sent_images: int,
    image_cap: int,
) -> int:
    """发一轮梦话（队列漂流 / 已学句 / 历史梦 / 归档图），与循环体内逻辑一致。返回更新后的 sent_images。"""
    item: DriftPayload | None = None
    if random.random() < dream_plugin_config.dream_drift_queue_tick_probability:
        try:
            item = q.get_nowait()
        except asyncio.QueueEmpty:
            item = None
    sent_queue_text = False
    sent_queue_image = False
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
        return sent_images

    prefer_echo = random.random() < dream_plugin_config.dream_prefer_learned_echo_probability
    if prefer_echo:
        if await _dream_tick_try_learned_echo(bot, group_id=group_id, sent_text_keys=sent_text_keys):
            return sent_images
        sent_h, inc = await _dream_tick_try_historical(
            bot,
            bot_id=bot_id,
            group_id=group_id,
            sent_text_keys=sent_text_keys,
            sent_image_keys=sent_image_keys,
            sent_images=sent_images,
            image_cap=image_cap,
        )
        sent_images += inc
        if sent_h:
            return sent_images
    else:
        sent_h, inc = await _dream_tick_try_historical(
            bot,
            bot_id=bot_id,
            group_id=group_id,
            sent_text_keys=sent_text_keys,
            sent_image_keys=sent_image_keys,
            sent_images=sent_images,
            image_cap=image_cap,
        )
        sent_images += inc
        if sent_h:
            return sent_images
        if await _dream_tick_try_learned_echo(bot, group_id=group_id, sent_text_keys=sent_text_keys):
            return sent_images

    if sent_images < image_cap and random.random() < dream_plugin_config.dream_archive_image_probability:
        from src.plugins.draw.draw_archive import random_archived_png_bytes

        for _ in range(_ARCHIVE_RESAMPLE_ATTEMPTS):
            data = await random_archived_png_bytes()
            if not data:
                break
            ik = dream_image_dedupe_key(data)
            if ik not in sent_image_keys:
                await _send_group_archived_draw_image(bot, group_id, data)
                sent_image_keys.add(ik)
                sent_images += 1
                break

    return sent_images


async def _dream_worker_loop(
    bot_id: int,
    group_id: int,
    *,
    sent_text_keys: set[str],
    sent_image_keys: set[str],
    sent_images: int,
) -> None:
    key = (bot_id, group_id)
    cfg = BotConfig(bot_id, group_id)
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
                lo = float(dream_plugin_config.dream_worker_sleep_min_sec)
                hi = float(dream_plugin_config.dream_worker_sleep_max_sec)
                await asyncio.sleep(random.uniform(lo, hi))
            if not await cfg.is_dreaming():
                break
            try:
                bot = get_bot(str(bot_id))
            except Exception as e:
                logger.debug(f"bot [{bot_id}] dream worker get_bot failed in group [{group_id}]: {e}")
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
                    logger.debug(f"bot [{bot_id}] dream drunk synergy send failed in group [{group_id}]: {e}")
                except Exception as e:
                    logger.warning(f"bot [{bot_id}] dream drunk synergy error in group [{group_id}]: {e}")
                continue
            try:
                sent_images = await _dream_worker_content_tick_once(
                    bot,
                    bot_id=bot_id,
                    group_id=group_id,
                    q=q,
                    sent_text_keys=sent_text_keys,
                    sent_image_keys=sent_image_keys,
                    sent_images=sent_images,
                    image_cap=image_cap,
                )
            except ActionFailed as e:
                logger.debug(f"bot [{bot_id}] dream send failed in group [{group_id}]: {e}")
            except Exception as e:
                logger.warning(f"bot [{bot_id}] dream worker tick error in group [{group_id}]: {e}")
        await cfg.stop_dream()
        await send_dream_wake_text(bot_id, group_id)
    except asyncio.CancelledError:
        raise
    finally:
        async with _dream_lock:
            _dream_active.discard(key)
        from src.platform.ingress.dream_host_gate import DREAM_HOST_GATE_PLUGIN
        from src.platform.multi_bot.dedup import needs_group_host_bot_gate, release_group_owned_gate_sync
        from src.platform.shard.coord.dream_drift import schedule_unregister_dream_active

        schedule_unregister_dream_active(bot_id, group_id)
        if needs_group_host_bot_gate():
            release_group_owned_gate_sync(DREAM_HOST_GATE_PLUGIN, group_id)
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


async def _dream_tick_try_historical(
    bot: Bot,
    *,
    bot_id: int,
    group_id: int,
    sent_text_keys: set[str],
    sent_image_keys: set[str],
    sent_images: int,
    image_cap: int,
) -> tuple[bool, int]:
    """尝试发一条 is_dream 历史。返回 (是否已发送, 本 tick 图片计数增量)。"""
    for _ in range(dream_plugin_config.dream_hist_resample_attempts):
        hist = await sample_historical_drift(bot_id=bot_id, consumer_group_id=group_id, exclude_group_id=group_id)
        if hist is None:
            hist = await sample_historical_drift(bot_id=bot_id, consumer_group_id=group_id, exclude_group_id=None)
        if hist is None:
            break
        if hist.image_bytes and sent_images < image_cap:
            ik = dream_image_dedupe_key(hist.image_bytes)
            if ik not in sent_image_keys:
                await _send_group_drift_image(bot, group_id, hist.nickname, hist.image_bytes)
                sent_image_keys.add(ik)
                await register_recent_drift_dedupe_key(group_id, ik)
                return True, 1
        if hist.text:
            tk = dream_text_dedupe_key(hist.text)
            if tk not in sent_text_keys:
                await _send_group_drift_text(bot, group_id, hist.nickname, hist.text)
                sent_text_keys.add(tk)
                await register_recent_drift_dedupe_key(group_id, tk)
                return True, 0
    return False, 0


async def _dream_tick_try_learned_echo(
    bot: Bot,
    *,
    group_id: int,
    sent_text_keys: set[str],
) -> bool:
    """从复读 Context 已学句抽一条，随机昵称当梦话发出。成功返回 True。"""
    for _ in range(dream_plugin_config.dream_echo_resample_attempts):
        line = await sample_learned_echo_line()
        if not line:
            break
        tk = dream_text_dedupe_key(line)
        if tk not in sent_text_keys:
            await _send_group_drift_text(bot, group_id, random_echo_nickname(), line)
            sent_text_keys.add(tk)
            return True
    return False


async def log_dream_chat_to_db(
    event: GroupMessageEvent,
    *,
    plain: str | None = None,
    nick: str | None = None,
) -> None:
    plain = (plain if plain is not None else event.get_plaintext()).strip()
    if not plain:
        plain = " "
    is_plain = "[CQ:" not in event.raw_message
    nick_source = nick if nick is not None else event.sender.card or event.sender.nickname or str(event.user_id)
    nick = nick_source.strip() or str(event.user_id)
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
        logger.debug(f"bot [{event.self_id}] dream message db insert failed in group [{event.group_id}]: {e}")
