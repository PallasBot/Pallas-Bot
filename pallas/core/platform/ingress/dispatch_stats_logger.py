from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
import time
import traceback

from nonebot.log import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ingress.dispatch_metrics import dispatch_metrics_snapshot

_task: asyncio.Task | None = None
_loop_lag_beat_task: asyncio.Task | None = None
_loop_lag_watchdog_thread: threading.Thread | None = None
_loop_lag_stop = threading.Event()
_loop_thread_id: int | None = None
_last_beat: float = 0.0
_last_task_hints: str = ""
_loop_lag_reports: int = 0
_LOOP_LAG_SAMPLE_SEC = 0.1
_LOOP_LAG_DEFAULT_WARN_MS = 1000.0
_LOOP_LAG_MAX_TASK_HINTS = 5


def loop_lag_report_count() -> int:
    """已上报的卡顿次数；供测试与排障确认 watchdog 确实在工作。"""
    return _loop_lag_reports


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


def _dispatch_stats_text(snap: dict) -> str:
    """入站调度统计：单行摘要，次要指标见 WebUI。"""
    scheduler = snap.get("conversation_scheduler") or {}
    send_q = snap.get("send_queue") or {}
    hot = snap.get("hotpath") or {}

    def ints(source: dict, *keys: str) -> tuple[int, ...]:
        return tuple(int(source.get(key) or 0) for key in keys)

    def ms(source: dict, key: str) -> str:
        value = source.get(key)
        return f"{value}ms" if value is not None else "-"

    group_messages, cmd, chat = ints(snap, "group_messages", "command_traffic", "chatter_traffic")
    overload, chat_degraded = ints(snap, "overload_signals", "chatter_overload_degraded")
    pending = int(scheduler.get("pending") or 0)
    llm_active, llm_waiting, llm_reserved = ints(scheduler, "llm_active", "llm_waiting", "llm_reserved")
    depth, max_depth = ints(send_q, "depth", "max_depth")

    return (
        f"ingress_dispatch：群消息 [{group_messages}]（命令 [{cmd}] / 闲聊 [{chat}]）"
        f" | P95 [{ms(snap, 'ingress_duration_ms_p95')}] / 全程 [{ms(snap, 'ingress_full_ms_p95')}]"
        f" | 过载 [{overload}] / 降级 [{chat_degraded}]"
        f" | 调度 [{pending}/{scheduler.get('max_pending')}] / LLM [{llm_active}/{llm_waiting}/{llm_reserved}]"
        f" / 发送 [{depth}/{max_depth}]"
        f" | bundle [{ms(hot, 'bundle_ms_p95')}] / db [{ms(hot, 'db_find_ms_p95')}]"
        f" / sql [{ms(hot, 'sql_total_ms_p95')}]"
    )


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


def loop_lag_warn_ms() -> float:
    """事件循环卡顿告警阈值；默认 1000ms，低于 200ms 会把正常调度抖动也当告警。"""
    raw = repo_env_raw_value("PALLAS_LOOP_LAG_WARN_MS")
    if raw is None:
        return _LOOP_LAG_DEFAULT_WARN_MS
    try:
        return max(200.0, float(str(raw).strip()))
    except ValueError:
        return _LOOP_LAG_DEFAULT_WARN_MS


def stalled_task_hints(limit: int = _LOOP_LAG_MAX_TASK_HINTS) -> list[str]:
    """取在途协程最内层调用点；不在事件循环线程上调用时返回空表。"""
    current = None
    try:
        tasks = asyncio.all_tasks()
    except RuntimeError:
        return []
    with contextlib.suppress(RuntimeError):
        current = asyncio.current_task()
    hints: list[str] = []
    for task in tasks:
        if task is current or task.done():
            continue
        try:
            stack = task.get_stack()
        except Exception:  # noqa: BLE001 - 拿不到栈不影响探测
            continue
        if not stack:
            continue
        summary = traceback.extract_stack(stack[-1])[-1]
        hints.append(f"{task.get_name()} @ {summary.filename}:{summary.lineno} in {summary.name}")
        if len(hints) >= limit:
            break
    return hints


def loop_thread_stack_hint() -> str:
    """取事件循环线程当前执行到的位置——同步调用卡住时，只有这里能指出阻塞点。"""
    frame = sys._current_frames().get(_loop_thread_id or -1)
    if frame is None:
        return "-"
    entries = traceback.extract_stack(frame, limit=8)
    frames = [f"{entry.filename}:{entry.lineno} in {entry.name}" for entry in reversed(entries)][:5]
    return " <- ".join(frames)


async def _loop_lag_beat() -> None:
    """只在循环可调度时更新心跳；被同步调用冻住时心跳停下，由 watchdog 线程负责取证。"""
    global _last_beat, _last_task_hints
    _last_beat = time.monotonic()
    tick = 0
    while True:
        await asyncio.sleep(_LOOP_LAG_SAMPLE_SEC)
        _last_beat = time.monotonic()
        tick += 1
        # 在途任务只能在循环里取；watchdog 线程用这份最近快照，卡住时它就是卡住前的现场。
        if tick % 5 == 0:
            _last_task_hints = " | ".join(stalled_task_hints())


def _loop_lag_watchdog() -> None:
    """独立线程看守心跳：循环自己卡住时无法自报，只有旁观者能拿到主线程栈。"""
    global _loop_lag_reports
    threshold = loop_lag_warn_ms() / 1000.0
    reported_beat = -1.0
    while not _loop_lag_stop.wait(_LOOP_LAG_SAMPLE_SEC):
        beat = _last_beat
        stale = time.monotonic() - beat
        if stale < threshold or beat == reported_beat:
            continue
        reported_beat = beat
        _loop_lag_reports += 1
        logger.warning(
            "[Loop] event loop stalled for [{:.0f}ms]; blocked at: {}; in-flight tasks: {}",
            stale * 1000.0,
            loop_thread_stack_hint(),
            _last_task_hints or "-",
        )


def start_loop_lag_probe() -> bool:
    global _loop_lag_beat_task, _loop_lag_watchdog_thread, _loop_thread_id, _last_beat
    if _loop_lag_beat_task is not None and not _loop_lag_beat_task.done():
        return False
    _last_beat = time.monotonic()
    _loop_thread_id = threading.get_ident()
    _loop_lag_stop.clear()
    _loop_lag_beat_task = asyncio.create_task(_loop_lag_beat(), name="pallas_loop_lag_beat")
    _loop_lag_watchdog_thread = threading.Thread(
        target=_loop_lag_watchdog,
        name="pallas-loop-lag-watchdog",
        daemon=True,
    )
    _loop_lag_watchdog_thread.start()
    logger.debug("事件循环卡顿探测已启动，告警阈值 [{}]ms", loop_lag_warn_ms())
    return True


async def stop_loop_lag_probe() -> None:
    global _loop_lag_beat_task, _loop_lag_watchdog_thread
    task = _loop_lag_beat_task
    _loop_lag_beat_task = None
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _loop_lag_stop.set()
    watchdog = _loop_lag_watchdog_thread
    _loop_lag_watchdog_thread = None
    if watchdog is not None:
        await asyncio.to_thread(watchdog.join, 1.0)


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
        log = logger.info if dispatch_stats_tick_notable(snap, prev=prev) else logger.debug
        prev = snap
        log(_dispatch_stats_text(snap))


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
