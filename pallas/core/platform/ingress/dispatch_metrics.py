from __future__ import annotations

import time
from collections import deque
from typing import Any

_COUNTERS = (
    "group_messages",
    "command_traffic",
    "chatter_traffic",
    "preprocessor_dropped",
    "route_index_hits",
    "route_index_fallbacks",
    "matchers_considered",
    "matchers_selected",
    "matchers_run",
    "lane_busy",
    "lane_wait_ms_total",
    "lane_wait_count",
    "overload_signals",
    "prefetch_paused",
)
_state: dict[str, int] = dict.fromkeys(_COUNTERS, 0)
_day_key = ""
_ingress_ms_samples: deque[float] = deque(maxlen=256)


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _rollover_if_needed() -> None:
    global _day_key
    today = _today_key()
    if _day_key == today:
        return
    _day_key = today
    for key in _COUNTERS:
        _state[key] = 0
    _ingress_ms_samples.clear()


def clear_dispatch_metrics_for_tests() -> None:
    global _day_key
    _day_key = ""
    for key in _COUNTERS:
        _state[key] = 0
    _ingress_ms_samples.clear()


def record_group_message_ingress(
    *,
    duration_ms: float,
    command_traffic: bool,
    matchers_considered: int,
    matchers_selected: int,
    matchers_run: int,
) -> None:
    _rollover_if_needed()
    _state["group_messages"] += 1
    if command_traffic:
        _state["command_traffic"] += 1
    else:
        _state["chatter_traffic"] += 1
    _state["matchers_considered"] += max(0, matchers_considered)
    _state["matchers_selected"] += max(0, matchers_selected)
    _state["matchers_run"] += max(0, matchers_run)
    if duration_ms >= 0:
        _ingress_ms_samples.append(float(duration_ms))


def record_preprocessor_dropped() -> None:
    _rollover_if_needed()
    _state["preprocessor_dropped"] += 1


def record_route_index_decision(*, index_hit: bool, fallback: bool) -> None:
    _rollover_if_needed()
    if index_hit:
        _state["route_index_hits"] += 1
    if fallback:
        _state["route_index_fallbacks"] += 1


def record_matcher_run() -> None:
    _rollover_if_needed()
    _state["matchers_run"] += 1


def record_lane_wait(wait_ms: float, *, busy: bool = False) -> None:
    _rollover_if_needed()
    if wait_ms > 0:
        _state["lane_wait_ms_total"] += int(wait_ms)
        _state["lane_wait_count"] += 1
    if busy:
        _state["lane_busy"] += 1


def record_overload_signal() -> None:
    _rollover_if_needed()
    _state["overload_signals"] += 1


def record_prefetch_paused() -> None:
    _rollover_if_needed()
    _state["prefetch_paused"] += 1


def ingress_duration_p95_ms() -> float | None:
    if not _ingress_ms_samples:
        return None
    ordered = sorted(_ingress_ms_samples)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95)))
    return round(float(ordered[idx]), 2)


def lane_wait_avg_ms() -> float | None:
    count = int(_state["lane_wait_count"])
    if count <= 0:
        return None
    return round(float(_state["lane_wait_ms_total"]) / count, 2)


def dispatch_alerts(*, p95_ms: float | None, pg_util: float | None) -> list[str]:
    alerts: list[str] = []
    if p95_ms is not None and p95_ms > 100.0:
        alerts.append("ingress_p95_over_100ms")
    if pg_util is not None and pg_util >= 0.85:
        alerts.append("pg_pool_over_85pct")
    return alerts


def dispatch_metrics_snapshot() -> dict[str, Any]:
    _rollover_if_needed()
    from pallas.core.foundation.db.pool_budget import pool_budget_status
    from pallas.core.platform.ingress.send_queue import send_queue_status

    p95 = ingress_duration_p95_ms()
    pool = pool_budget_status()
    pg_util = pool.get("utilization")
    counters = {key: int(_state[key]) for key in _COUNTERS}
    return build_dispatch_metrics_payload(
        day_key=_day_key or _today_key(),
        counters=counters,
        ingress_duration_ms_p95=p95,
        send_queue=send_queue_status(),
        pool_budget=pool,
        pg_util=pg_util if isinstance(pg_util, float) else None,
    )


def build_dispatch_metrics_payload(
    *,
    day_key: str,
    counters: dict[str, int],
    ingress_duration_ms_p95: float | None,
    send_queue: dict[str, Any],
    pool_budget: dict[str, Any],
    pg_util: float | None,
) -> dict[str, Any]:
    group_messages = int(counters.get("group_messages") or 0)
    considered = int(counters.get("matchers_considered") or 0)
    selected = int(counters.get("matchers_selected") or 0)
    route_hits = int(counters.get("route_index_hits") or 0)
    route_fallbacks = int(counters.get("route_index_fallbacks") or 0)
    lane_wait_count = int(counters.get("lane_wait_count") or 0)
    lane_wait_total = int(counters.get("lane_wait_ms_total") or 0)
    lane_wait_avg = round(float(lane_wait_total) / lane_wait_count, 2) if lane_wait_count > 0 else None
    return {
        "day_key": day_key,
        **{key: int(counters.get(key) or 0) for key in _COUNTERS},
        "lane_wait_ms_avg": lane_wait_avg,
        "ingress_duration_ms_p95": ingress_duration_ms_p95,
        "send_queue": send_queue,
        "pool_budget": pool_budget,
        "alerts": dispatch_alerts(p95_ms=ingress_duration_ms_p95, pg_util=pg_util),
        "matchers_selected_ratio": round(selected / considered, 4) if considered else None,
        "avg_matchers_per_message": round(selected / group_messages, 2) if group_messages else None,
        "route_index_hit_ratio": round(route_hits / group_messages, 4) if group_messages else None,
        "route_index_fallback_ratio": round(route_fallbacks / group_messages, 4) if group_messages else None,
    }


def merge_send_queue_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "enabled": True,
        "installed": False,
        "depth": 0,
        "depth_live": 0,
        "sent": 0,
        "dropped": 0,
        "max_depth": 0,
        "workers": 0,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        merged["installed"] = bool(merged["installed"] or row.get("installed"))
        if row.get("enabled") is False:
            merged["enabled"] = False
        merged["depth"] += int(row.get("depth") or 0)
        merged["depth_live"] += int(row.get("depth_live") or row.get("depth") or 0)
        merged["sent"] += int(row.get("sent") or 0)
        merged["dropped"] += int(row.get("dropped") or 0)
        merged["max_depth"] += int(row.get("max_depth") or 0)
        merged["workers"] += int(row.get("workers") or 0)
    return merged


def merge_pool_budget_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    util_max: float | None = None
    capacity_total = 0
    checked_out_total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        util = row.get("utilization")
        if isinstance(util, float):
            util_max = util if util_max is None else max(util_max, util)
        cap = row.get("capacity")
        if isinstance(cap, int):
            capacity_total += cap
        checked = row.get("checked_out")
        if isinstance(checked, int):
            checked_out_total += checked
    out: dict[str, Any] = {}
    if capacity_total > 0:
        out["capacity"] = capacity_total
    if checked_out_total > 0:
        out["checked_out"] = checked_out_total
    if util_max is not None:
        out["utilization"] = round(util_max, 4)
    elif capacity_total > 0 and checked_out_total > 0:
        out["utilization"] = round(checked_out_total / capacity_total, 4)
    return out


def merge_dispatch_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dispatch_metrics_snapshot()
    counters = dict.fromkeys(_COUNTERS, 0)
    p95_values: list[float] = []
    send_rows: list[dict[str, Any]] = []
    pool_rows: list[dict[str, Any]] = []
    day_key = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        for key in _COUNTERS:
            counters[key] += int(row.get(key) or 0)
        p95 = row.get("ingress_duration_ms_p95")
        if isinstance(p95, (int, float)):
            p95_values.append(float(p95))
        send = row.get("send_queue")
        if isinstance(send, dict):
            send_rows.append(send)
        pool = row.get("pool_budget")
        if isinstance(pool, dict):
            pool_rows.append(pool)
    p95_cluster = round(max(p95_values), 2) if p95_values else None
    pool_merged = merge_pool_budget_snapshots(pool_rows)
    pg_util = pool_merged.get("utilization")
    return build_dispatch_metrics_payload(
        day_key=day_key or _today_key(),
        counters=counters,
        ingress_duration_ms_p95=p95_cluster,
        send_queue=merge_send_queue_snapshots(send_rows),
        pool_budget=pool_merged,
        pg_util=pg_util if isinstance(pg_util, float) else None,
    )
