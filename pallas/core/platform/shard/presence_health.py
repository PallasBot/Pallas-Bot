"""Presence QQ 会话健康探测：踢出僵尸 WS。"""

from __future__ import annotations

import asyncio
import time
from itertools import starmap
from typing import Any

from nonebot import logger

STATUS_PROBE_TIMEOUT_SEC = 5.0
STATUS_FAIL_THRESHOLD = 3
# 最短探测间隔：hist flush 约 30s 一次，此处再限到 60s，降低 OneBot 压力。
STATUS_PROBE_MIN_INTERVAL_SEC = 60.0
_PROBE_CONCURRENCY = 8

_fail_counts: dict[int, int] = {}
_quarantine: set[int] = set()
_last_probe_mono: float = 0.0


def reset_presence_health_state_for_tests() -> None:
    global _last_probe_mono
    _fail_counts.clear()
    _quarantine.clear()
    _last_probe_mono = 0.0


def health_quarantine_qq_ids() -> frozenset[int]:
    return frozenset(_quarantine)


def clear_health_quarantine(qq: int) -> None:
    qid = int(qq)
    _quarantine.discard(qid)
    _fail_counts.pop(qid, None)


def evaluate_get_status_healthy(raw: object) -> bool:
    """OneBot get_status data 是否表示 QQ 会话健康。"""
    if not isinstance(raw, dict):
        return False
    if raw.get("online") is False:
        return False
    if "good" in raw and raw.get("good") is False:
        return False
    if "online" not in raw and "good" not in raw:
        # 空/未知结构：不算健康，避免误放行
        return False
    return True


def record_health_probe_result(qq: int, *, ok: bool) -> bool:
    """记录探测结果。返回 True 表示本轮达到阈值、应踢出 presence。"""
    qid = int(qq)
    if ok:
        _fail_counts.pop(qid, None)
        _quarantine.discard(qid)
        return False
    count = int(_fail_counts.get(qid, 0)) + 1
    _fail_counts[qid] = count
    if count >= int(STATUS_FAIL_THRESHOLD):
        _quarantine.add(qid)
        return True
    return False


async def probe_bot_get_status_healthy(bot: Any) -> bool:
    try:
        raw = await asyncio.wait_for(
            bot.call_api("get_status"),
            timeout=float(STATUS_PROBE_TIMEOUT_SEC),
        )
    except Exception as e:
        logger.debug(
            "presence_health get_status failed bot={}: {}",
            getattr(bot, "self_id", "?"),
            e,
        )
        return False
    return evaluate_get_status_healthy(raw)


async def apply_presence_qq_health_probes(*, force: bool = False) -> list[int]:
    """对本机已连 OneBot 牛做 get_status；达阈值则清 presence。返回本轮踢出的 QQ。"""
    global _last_probe_mono

    from nonebot import get_bots

    from pallas.core.platform.shard import context as shard_ctx
    from pallas.core.platform.shard.presence import note_worker_bot_disconnected_sync

    if not shard_ctx.sharding_active():
        return []

    now = time.monotonic()
    if not force and _last_probe_mono > 0 and (now - _last_probe_mono) < float(STATUS_PROBE_MIN_INTERVAL_SEC):
        return []
    _last_probe_mono = now

    bots = get_bots()
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)
    kicked: list[int] = []

    async def one(key: str, bot: Any) -> None:
        try:
            qq = int(key)
        except (TypeError, ValueError):
            return
        if not str(getattr(bot, "self_id", "") or "").isnumeric():
            return
        async with sem:
            ok = await probe_bot_get_status_healthy(bot)
        if record_health_probe_result(qq, ok=ok):
            note_worker_bot_disconnected_sync(qq=qq)
            kicked.append(qq)
            logger.warning(
                "presence_health: qq={} quarantined after {} failed get_status",
                qq,
                STATUS_FAIL_THRESHOLD,
            )

    await asyncio.gather(*starmap(one, bots.items()))
    return kicked
