from __future__ import annotations

import asyncio
import contextlib

from nonebot.log import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ingress.dispatch_metrics import dispatch_metrics_snapshot

_task: asyncio.Task | None = None


def dispatch_stats_log_interval_sec() -> float:
    raw = repo_env_raw_value("PALLAS_DISPATCH_STATS_LOG_INTERVAL_SEC")
    if raw is None:
        return 60.0
    try:
        return max(10.0, float(str(raw).strip()))
    except ValueError:
        return 60.0


def _counter_delta(snap: dict, prev: dict | None, key: str) -> int:
    cur = int(snap.get(key) or 0)
    if prev is None:
        return 0
    return max(0, cur - int(prev.get(key) or 0))


def _send_queue_dropped(snap: dict) -> int:
    return int((snap.get("send_queue") or {}).get("dropped") or 0)


def dispatch_stats_tick_notable(snap: dict, *, prev: dict | None = None) -> bool:
    """健康周期票走 DEBUG；本周期 busy·丢弃增量 / 排队过半 / 高 p95 才 INFO。

    不看 ``is_overloaded()`` / ``overload_signals``：热群下 matcher 阈值会常亮过载，
    每分钟 INFO 无助于排障。p95 / lane_wait 粘滞，仅本周期有群消息时抬 INFO。
    """
    lane_busy_delta = _counter_delta(snap, prev, "lane_busy")
    dropped = _send_queue_dropped(snap)
    dropped_delta = dropped if prev is None else max(0, dropped - _send_queue_dropped(prev))
    if lane_busy_delta > 0 or dropped_delta > 0:
        return True
    send_q = snap.get("send_queue") or {}
    depth = int(send_q.get("depth") or 0)
    max_depth = int(send_q.get("max_depth") or 0)
    if max_depth > 0 and depth >= max(1, max_depth // 2):
        return True
    gm_delta = _counter_delta(snap, prev, "group_messages")
    if gm_delta <= 0 and prev is not None:
        return False
    try:
        p95 = float(snap.get("ingress_duration_ms_p95") or 0)
    except (TypeError, ValueError):
        p95 = 0.0
    if p95 >= 2000.0:
        return True
    try:
        lane_wait = float(snap.get("lane_wait_ms_avg") or 0)
    except (TypeError, ValueError):
        lane_wait = 0.0
    return lane_wait >= 50.0


async def dispatch_stats_log_loop() -> None:
    interval = dispatch_stats_log_interval_sec()
    prev: dict | None = None
    while True:
        await asyncio.sleep(interval)
        snap = dispatch_metrics_snapshot()
        group_messages = int(snap.get("group_messages") or 0)
        if group_messages <= 0:
            prev = snap
            continue
        considered = int(snap.get("matchers_considered") or 0)
        selected = int(snap.get("matchers_selected") or 0)
        log = logger.info if dispatch_stats_tick_notable(snap, prev=prev) else logger.debug
        prev = snap
        log(
            "ingress_dispatch: stats group_messages={} cmd={} chat={} route_hit={} route_fallback={} "
            "matchers {}/{} run={} p95={}ms lane_wait_avg={} overload={} lane_busy={} "
            "send_q={}/{} dropped={}",
            group_messages,
            int(snap.get("command_traffic") or 0),
            int(snap.get("chatter_traffic") or 0),
            int(snap.get("route_index_hits") or 0),
            int(snap.get("route_index_fallbacks") or 0),
            selected,
            considered,
            int(snap.get("matchers_run") or 0),
            snap.get("ingress_duration_ms_p95"),
            snap.get("lane_wait_ms_avg"),
            int(snap.get("overload_signals") or 0),
            int(snap.get("lane_busy") or 0),
            (snap.get("send_queue") or {}).get("depth"),
            (snap.get("send_queue") or {}).get("max_depth"),
            (snap.get("send_queue") or {}).get("dropped"),
        )


def start_dispatch_stats_logger() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(dispatch_stats_log_loop(), name="ingress_dispatch_stats")


async def stop_dispatch_stats_logger() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
