"""PG 连接池诊断：周期汇总 + 慢持连统计。"""

from __future__ import annotations

import asyncio
import inspect
import sys
from collections import Counter
from typing import Any

from nonebot import get_driver, logger

from src.foundation.config.repo_settings import repo_env_raw_value

_TICK_SEC_DEFAULT = 300.0
_diag_task: asyncio.Task[None] | None = None
_bound = False

_slow_by_caller: Counter[str] = Counter()
_slow_session_total: int = 0
_slow_hold_max_ms: float = 0.0
_mirror_skipped_pressure: int = 0
_CALLER_SCAN_SKIP_SUFFIXES = ("/foundation/db/repository_pg.py", "/contextlib.py")
_CALLER_SCAN_MAX_DEPTH = 16


def session_hold_warn_ms() -> float:
    raw = repo_env_raw_value("PG_SESSION_HOLD_WARN_MS")
    if raw is not None:
        try:
            return max(50.0, float(str(raw).strip()))
        except ValueError:
            pass
    return 500.0


def pool_diag_tick_sec() -> float:
    raw = repo_env_raw_value("PG_POOL_DIAG_TICK_SEC")
    if raw is not None:
        try:
            return max(30.0, float(str(raw).strip()))
        except ValueError:
            pass
    return _TICK_SEC_DEFAULT


def pool_diag_tick_notable(
    *,
    under_pressure: bool,
    idle_in_tx: int | None,
    slow_sessions: int,
    remote_skipped_pressure: int,
    remote_skipped_busy: int,
    mirror_skip: int,
    learn_pool_wait: int,
) -> bool:
    if under_pressure or slow_sessions > 0:
        return True
    if idle_in_tx and idle_in_tx > 0:
        return True
    if remote_skipped_pressure > 0 or remote_skipped_busy > 0:
        return True
    if mirror_skip > 0 or learn_pool_wait > 0:
        return True
    return False


def _is_ignored_caller_path(path: str) -> bool:
    return path.endswith(_CALLER_SCAN_SKIP_SUFFIXES) or "/site-packages/" in path


def _format_caller_hint(function: str, filename: str, lineno: int) -> str:
    path = filename.replace("\\", "/")
    parts = path.rsplit("/", 2)
    label = "/".join(parts[-2:]) if len(parts) >= 2 else path
    return f"{function}@{label}:{lineno}"


def _pg_session_caller_hint_from_frame() -> str | None:
    getframe = getattr(sys, "_getframe", None)
    if getframe is None:
        return None
    try:
        frame = getframe(2)
    except ValueError:
        return None
    for _ in range(_CALLER_SCAN_MAX_DEPTH):
        if frame is None:
            break
        code = frame.f_code
        path = code.co_filename.replace("\\", "/")
        if not _is_ignored_caller_path(path):
            return _format_caller_hint(code.co_name, code.co_filename, frame.f_lineno)
        frame = frame.f_back
    return None


def _pg_session_caller_hint_from_stack() -> str:
    for frame_info in inspect.stack()[2 : 2 + _CALLER_SCAN_MAX_DEPTH]:
        path = frame_info.filename.replace("\\", "/")
        if _is_ignored_caller_path(path):
            continue
        return _format_caller_hint(frame_info.function, frame_info.filename, frame_info.lineno)
    return "unknown"


def pg_session_caller_hint_entry() -> str:
    """在 get_session 入口捕获调用方。"""
    hint = _pg_session_caller_hint_from_frame()
    if hint is not None:
        return hint
    return _pg_session_caller_hint_from_stack()


def pg_session_caller_hint() -> str:
    return pg_session_caller_hint_entry()


def note_slow_pg_session(held_ms: float, caller: str) -> None:
    global _slow_session_total, _slow_hold_max_ms
    _slow_session_total += 1
    _slow_hold_max_ms = max(_slow_hold_max_ms, held_ms)
    _slow_by_caller[caller] += 1


def note_mirror_skipped_pressure() -> None:
    global _mirror_skipped_pressure
    _mirror_skipped_pressure += 1


async def pg_idle_in_transaction_count() -> int | None:
    from sqlalchemy import text

    from src.foundation.db.repository_pg import is_pg_initialized, pg_engine

    if not is_pg_initialized():
        return None
    engine = pg_engine()
    if engine is None:
        return None
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND state = 'idle in transaction'"
                )
            )
            val = result.scalar()
            return int(val) if val is not None else 0
    except Exception as e:
        logger.debug("pg idle-in-tx probe failed: {}", e)
        return None


def learn_runtime_snapshot() -> dict[str, Any]:
    try:
        from src.plugins.repeater.learn_queue import drain_learn_pause_stats, learn_concurrency, learn_queue

        q = learn_queue()
        return {
            "learn_effective": learn_concurrency(),
            "learn_queue_size": q.qsize(),
            "learn_pool_wait_spins": drain_learn_pause_stats(),
        }
    except Exception:
        return {}


async def emit_pool_diagnostics_tick() -> None:
    global _slow_session_total, _mirror_skipped_pressure, _slow_hold_max_ms

    from src.features.corpus.remote_budget import drain_remote_corpus_skip_counters
    from src.foundation.db.pg_activity_diagnostics import (
        collect_pg_activity_snapshot,
        maybe_emit_pg_activity_diagnostics,
        wait_summary,
    )
    from src.foundation.db.pool_budget import pool_budget_status

    budget = pool_budget_status()
    live = budget.get("live") or {}
    util = budget.get("utilization")
    util_pct = f"{util * 100:.0f}%" if util is not None else "n/a"
    idle_tx = await pg_idle_in_transaction_count()
    remote = drain_remote_corpus_skip_counters()
    learn = learn_runtime_snapshot()
    activity = await collect_pg_activity_snapshot()
    wait_s = wait_summary(activity)

    slow_top = ", ".join(f"{k}={v}" for k, v in _slow_by_caller.most_common(3))
    if not slow_top:
        slow_top = "-"

    skipped_pressure = int(remote.get("skipped_pressure", 0))
    skipped_busy = int(remote.get("skipped_busy", 0))
    learn_pool_wait = int(learn.get("learn_pool_wait_spins", 0) or 0)
    notable = pool_diag_tick_notable(
        under_pressure=bool(budget.get("under_pressure")),
        idle_in_tx=idle_tx,
        slow_sessions=_slow_session_total,
        remote_skipped_pressure=skipped_pressure,
        remote_skipped_busy=skipped_busy,
        mirror_skip=_mirror_skipped_pressure,
        learn_pool_wait=learn_pool_wait,
    )
    diag_log = logger.info if notable else logger.debug
    diag_log(
        "pg pool diag: checked_out={}/{} util={} idle_in_tx={} pg_wait=[{}] "
        "remote_skip_pressure={} remote_skip_busy={} mirror_skip={} "
        "slow_sessions={} slow_max_ms={:.0f} learn_q={} learn_pool_wait={} slow_top=[{}]",
        live.get("checked_out", "?"),
        live.get("capacity", budget.get("capacity", "?")),
        util_pct,
        idle_tx if idle_tx is not None else "?",
        wait_s,
        skipped_pressure,
        skipped_busy,
        _mirror_skipped_pressure,
        _slow_session_total,
        _slow_hold_max_ms,
        learn.get("learn_queue_size", "?"),
        learn_pool_wait,
        slow_top,
    )

    await maybe_emit_pg_activity_diagnostics(
        activity,
        under_pressure=bool(budget.get("under_pressure")),
        idle_in_tx_count=idle_tx,
        slow_sessions=_slow_session_total,
        slow_max_ms=_slow_hold_max_ms,
    )

    _slow_by_caller.clear()
    _slow_session_total = 0
    _slow_hold_max_ms = 0.0
    _mirror_skipped_pressure = 0


async def pool_diagnostics_loop() -> None:
    await asyncio.sleep(pool_diag_tick_sec())
    while True:
        try:
            await emit_pool_diagnostics_tick()
        except Exception as e:
            logger.warning("pg pool diagnostics tick failed: {}", e)
        await asyncio.sleep(pool_diag_tick_sec())


def bind_pg_pool_diagnostics() -> None:
    global _bound
    if _bound:
        return
    _bound = True
    driver = get_driver()

    @driver.on_shutdown
    async def _stop_pg_pool_diagnostics() -> None:
        global _diag_task
        if _diag_task is None:
            return
        _diag_task.cancel()
        await asyncio.gather(_diag_task, return_exceptions=True)
        _diag_task = None


def start_pg_pool_diagnostics_task() -> None:
    global _diag_task
    if _diag_task is not None and not _diag_task.done():
        return
    _diag_task = asyncio.create_task(pool_diagnostics_loop(), name="pg_pool_diagnostics")
    logger.debug(
        "pg pool diagnostics started (tick={}s, session_hold_warn={}ms)",
        int(pool_diag_tick_sec()),
        int(session_hold_warn_ms()),
    )


async def reset_pg_pool_diagnostics_for_tests() -> None:
    global _diag_task, _slow_by_caller, _slow_session_total, _slow_hold_max_ms, _mirror_skipped_pressure
    if _diag_task is not None:
        _diag_task.cancel()
        await asyncio.gather(_diag_task, return_exceptions=True)
        _diag_task = None
    _slow_by_caller.clear()
    _slow_session_total = 0
    _slow_hold_max_ms = 0.0
    _mirror_skipped_pressure = 0
