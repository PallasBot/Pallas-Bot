"""PG 侧活动诊断：pg_stat_activity / wait_event / 阻塞链 / pg_stat_statements。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

_STATE_COUNTS_SQL = """
SELECT coalesce(state, '?') AS state, count(*)::int AS cnt
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
GROUP BY state
ORDER BY cnt DESC
"""

_WAIT_BREAKDOWN_SQL = """
SELECT
    coalesce(wait_event_type, 'none') AS wait_event_type,
    coalesce(wait_event, '-') AS wait_event,
    count(*)::int AS cnt
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
GROUP BY wait_event_type, wait_event
ORDER BY cnt DESC
"""

_BLOCKERS_SQL = """
SELECT
    blocked_activity.pid AS blocked_pid,
    blocking_activity.pid AS blocking_pid,
    blocked_activity.wait_event_type AS blocked_wait_type,
    blocked_activity.wait_event AS blocked_wait,
    round(
        EXTRACT(EPOCH FROM (clock_timestamp() - blocked_activity.query_start))::numeric,
        1
    ) AS blocked_sec,
    left(regexp_replace(blocked_activity.query, E'\\s+', ' ', 'g'), 160) AS blocked_query,
    round(
        EXTRACT(EPOCH FROM (clock_timestamp() - blocking_activity.query_start))::numeric,
        1
    ) AS blocking_sec,
    left(regexp_replace(blocking_activity.query, E'\\s+', ' ', 'g'), 160) AS blocking_query
FROM pg_catalog.pg_stat_activity AS blocked_activity
CROSS JOIN LATERAL unnest(pg_catalog.pg_blocking_pids(blocked_activity.pid)) AS blocking_pid
JOIN pg_catalog.pg_stat_activity AS blocking_activity
  ON blocking_activity.pid = blocking_pid
WHERE blocked_activity.datname = current_database()
  AND blocked_activity.pid <> pg_backend_pid()
"""

_SLOW_ACTIVE_SQL = """
SELECT
    pid,
    state,
    wait_event_type,
    wait_event,
    round(
        EXTRACT(EPOCH FROM (clock_timestamp() - query_start))::numeric,
        2
    ) AS query_sec,
    left(regexp_replace(query, E'\\s+', ' ', 'g'), 160) AS query_preview
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND state = 'active'
  AND query NOT ILIKE '%pg_stat_activity%'
  AND query NOT ILIKE '%pg_stat_statements%'
  AND query NOT ILIKE '%pg_blocking_pids%'
ORDER BY query_start ASC
LIMIT :limit
"""

_IDLE_IN_TX_SQL = """
SELECT
    pid,
    round(
        EXTRACT(EPOCH FROM (clock_timestamp() - state_change))::numeric,
        1
    ) AS idle_sec,
    left(regexp_replace(query, E'\\s+', ' ', 'g'), 160) AS query_preview
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND state = 'idle in transaction'
ORDER BY state_change ASC
LIMIT :limit
"""

_STATEMENTS_TOP_SQL = """
SELECT
    left(regexp_replace(query, E'\\s+', ' ', 'g'), 160) AS query_preview,
    calls::bigint AS calls,
    round(mean_exec_time::numeric, 1) AS mean_ms,
    round(total_exec_time::numeric, 1) AS total_ms
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY mean_exec_time DESC
LIMIT :limit
"""


def pg_activity_diag_mode() -> str:
    raw = repo_env_raw_value("PG_ACTIVITY_DIAG_ENABLED")
    if raw is None:
        return "auto"
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return "always"
    if s in ("0", "false", "no", "off"):
        return "off"
    return "auto"


def pg_activity_diag_always() -> bool:
    raw = repo_env_raw_value("PG_ACTIVITY_DIAG_ALWAYS")
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def pg_activity_slow_query_sec() -> float:
    raw = repo_env_raw_value("PG_ACTIVITY_SLOW_QUERY_SEC")
    if raw is not None:
        try:
            return max(0.5, float(str(raw).strip()))
        except ValueError:
            pass
    return 2.0


def pg_stat_statements_top_n() -> int:
    raw = repo_env_raw_value("PG_STATEMENTS_TOP_N")
    if raw is not None:
        try:
            return max(1, min(20, int(str(raw).strip())))
        except ValueError:
            pass
    return 5


@dataclass
class PgActivitySnapshot:
    state_counts: dict[str, int] = field(default_factory=dict)
    wait_breakdown: list[tuple[str, str, int]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    slow_active: list[dict[str, Any]] = field(default_factory=list)
    idle_in_tx: list[dict[str, Any]] = field(default_factory=list)
    statements_top: list[dict[str, Any]] = field(default_factory=list)
    statements_available: bool = False
    error: str | None = None


def wait_summary(snapshot: PgActivitySnapshot) -> str:
    parts: list[str] = []
    for wet, we, cnt in snapshot.wait_breakdown:
        if wet in ("none", "") or cnt <= 0:
            continue
        label = wet if we in ("-", "") else f"{wet}/{we}"
        parts.append(f"{label}:{cnt}")
    return "|".join(parts) if parts else "-"


def classify_pg_bottleneck(snapshot: PgActivitySnapshot) -> str:
    if snapshot.blockers:
        return "lock_contention"
    threshold = pg_activity_slow_query_sec()
    slow = [r for r in snapshot.slow_active if float(r.get("query_sec") or 0) >= threshold]
    lock_waits = sum(cnt for wet, _we, cnt in snapshot.wait_breakdown if wet == "Lock")
    io_waits = sum(cnt for wet, _we, cnt in snapshot.wait_breakdown if wet == "IO")
    buffer_waits = sum(cnt for wet, we, cnt in snapshot.wait_breakdown if wet == "LWLock" and "Buffer" in (we or ""))
    if lock_waits >= 1:
        return "lock_contention"
    if io_waits + buffer_waits >= 2:
        return "io_wait"
    if snapshot.idle_in_tx:
        return "idle_in_transaction"
    if slow:
        waiting = sum(1 for row in slow if row.get("wait_event_type") not in (None, "", "none"))
        if waiting >= max(1, len(slow) // 2):
            dominant = max(
                (str(row.get("wait_event_type") or "wait") for row in slow),
                key=lambda k: sum(1 for row in slow if str(row.get("wait_event_type") or "wait") == k),
            )
            return f"wait_{dominant.lower()}"
        return "slow_query"
    return "unknown"


def should_emit_pg_activity_detail(
    snapshot: PgActivitySnapshot,
    *,
    under_pressure: bool,
    idle_in_tx_count: int | None,
    slow_sessions: int,
    slow_max_ms: float,
) -> bool:
    mode = pg_activity_diag_mode()
    if mode == "off":
        return False
    if mode == "always" or pg_activity_diag_always():
        return True
    threshold = pg_activity_slow_query_sec()
    if under_pressure or slow_sessions > 0 or slow_max_ms >= session_hold_warn_ms():
        return True
    if idle_in_tx_count and idle_in_tx_count > 0:
        return True
    if snapshot.blockers or snapshot.idle_in_tx:
        return True
    if any(float(r.get("query_sec") or 0) >= threshold for r in snapshot.slow_active):
        return True
    for wet, _we, cnt in snapshot.wait_breakdown:
        if wet in ("Lock", "IO") and cnt >= 1:
            return True
    return False


def session_hold_warn_ms() -> float:
    from pallas.core.foundation.db.pool_diagnostics import session_hold_warn_ms as base

    return base()


def format_pg_activity_detail(snapshot: PgActivitySnapshot) -> str:
    lines: list[str] = []
    bottleneck = classify_pg_bottleneck(snapshot)
    lines.append(f"bottleneck={bottleneck}")

    if snapshot.state_counts:
        state_s = ", ".join(f"{k}={v}" for k, v in sorted(snapshot.state_counts.items()))
        lines.append(f"states: {state_s}")

    if snapshot.wait_breakdown:
        wait_s = ", ".join(f"{wet}/{we}={cnt}" for wet, we, cnt in snapshot.wait_breakdown[:8])
        lines.append(f"wait_events: {wait_s}")

    lines.extend(
        "block: blocked_pid={blocked_pid} wait={blocked_wait_type}/{blocked_wait} "
        "sec={blocked_sec} q={blocked_query!r} <- blocking_pid={blocking_pid} "
        "sec={blocking_sec} q={blocking_query!r}".format(**row)
        for row in snapshot.blockers[:5]
    )

    threshold = pg_activity_slow_query_sec()
    lines.extend(
        "slow_active: pid={pid} sec={query_sec} wait={wait_event_type}/{wait_event} q={query_preview!r}".format(**row)
        for row in snapshot.slow_active[:5]
        if float(row.get("query_sec") or 0) >= threshold
    )

    lines.extend(
        "idle_in_tx: pid={pid} sec={idle_sec} last_q={query_preview!r}".format(**row) for row in snapshot.idle_in_tx[:5]
    )

    if snapshot.statements_available:
        lines.extend(
            "stat_top_mean: mean_ms={mean_ms} calls={calls} total_ms={total_ms} q={query_preview!r}".format(**row)
            for row in snapshot.statements_top[: pg_stat_statements_top_n()]
        )
    elif not snapshot.statements_top:
        lines.append("stat_top_mean: pg_stat_statements unavailable")

    if snapshot.error:
        lines.append(f"probe_error={snapshot.error}")

    return "\n ".join(lines)


async def collect_pg_activity_snapshot() -> PgActivitySnapshot:
    from sqlalchemy import text

    from pallas.core.foundation.db.repository_pg import is_pg_initialized, pg_engine

    snap = PgActivitySnapshot()
    if not is_pg_initialized():
        snap.error = "pg_not_initialized"
        return snap
    engine = pg_engine()
    if engine is None:
        snap.error = "pg_engine_missing"
        return snap

    slow_limit = max(5, pg_stat_statements_top_n())
    try:
        async with engine.connect() as conn:
            for state, cnt in (await conn.execute(text(_STATE_COUNTS_SQL))).all():
                snap.state_counts[str(state)] = int(cnt)

            for wet, we, cnt in (await conn.execute(text(_WAIT_BREAKDOWN_SQL))).all():
                snap.wait_breakdown.append((str(wet), str(we), int(cnt)))

            blocker_rows = (await conn.execute(text(_BLOCKERS_SQL))).mappings().all()
            snap.blockers = [dict(r) for r in blocker_rows]

            slow_rows = (await conn.execute(text(_SLOW_ACTIVE_SQL), {"limit": slow_limit})).mappings().all()
            snap.slow_active = [dict(r) for r in slow_rows]

            idle_rows = (await conn.execute(text(_IDLE_IN_TX_SQL), {"limit": slow_limit})).mappings().all()
            snap.idle_in_tx = [dict(r) for r in idle_rows]

            try:
                stmt_rows = (
                    (
                        await conn.execute(
                            text(_STATEMENTS_TOP_SQL),
                            {"limit": pg_stat_statements_top_n()},
                        )
                    )
                    .mappings()
                    .all()
                )
                snap.statements_top = [dict(r) for r in stmt_rows]
                snap.statements_available = True
            except Exception as e:
                logger.debug("pg_stat_statements probe skipped: {}", e)
    except Exception as e:
        snap.error = str(e)
        logger.debug("pg activity snapshot failed: {}", e)
    return snap


async def maybe_emit_pg_activity_diagnostics(
    snapshot: PgActivitySnapshot,
    *,
    under_pressure: bool,
    idle_in_tx_count: int | None,
    slow_sessions: int,
    slow_max_ms: float,
) -> None:
    if pg_activity_diag_mode() == "off":
        return
    if not should_emit_pg_activity_detail(
        snapshot,
        under_pressure=under_pressure,
        idle_in_tx_count=idle_in_tx_count,
        slow_sessions=slow_sessions,
        slow_max_ms=slow_max_ms,
    ):
        return
    detail = format_pg_activity_detail(snapshot)
    logger.debug("pg activity detail:\n {}", detail)
