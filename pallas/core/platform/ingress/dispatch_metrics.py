from __future__ import annotations

import time
from collections import deque
from typing import Any

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ingress.route_candidate_metrics import route_candidate_metrics_snapshot
from pallas.core.platform.ingress.snapshot_health import ingress_snapshot_health

_COUNTERS = (
    "group_messages",
    "command_traffic",
    "chatter_traffic",
    "preprocessor_dropped",
    "chatter_overload_dropped",
    "chatter_overload_degraded",
    "stale_messages_dropped",
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
_INGRESS_SAMPLE_WINDOW_SEC = 600.0
_ingress_ms_samples: deque[tuple[float, float]] = deque()
_ingress_full_ms_samples: deque[tuple[float, float]] = deque()


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def ingress_sample_window_sec() -> float:
    raw = repo_env_raw_value("PALLAS_INGRESS_P95_WINDOW_SEC")
    if raw is None:
        return _INGRESS_SAMPLE_WINDOW_SEC
    try:
        return max(60.0, float(str(raw).strip()))
    except ValueError:
        return _INGRESS_SAMPLE_WINDOW_SEC


def _rollover_if_needed() -> None:
    global _day_key
    today = _today_key()
    if _day_key == today:
        return
    _day_key = today
    for key in _COUNTERS:
        _state[key] = 0
    _ingress_ms_samples.clear()
    _ingress_full_ms_samples.clear()


def clear_dispatch_metrics_for_tests() -> None:
    global _day_key
    _day_key = ""
    for key in _COUNTERS:
        _state[key] = 0
    _ingress_ms_samples.clear()
    _ingress_full_ms_samples.clear()


def record_group_message_ingress(
    *,
    duration_ms: float,
    full_duration_ms: float | None = None,
    command_traffic: bool,
    matchers_considered: int,
    matchers_selected: int,
    matchers_run: int,
    record_p95: bool = True,
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
    if not record_p95:
        return
    now = time.monotonic()
    if duration_ms >= 0:
        _ingress_ms_samples.append((now, float(duration_ms)))
    if full_duration_ms is not None and full_duration_ms >= 0:
        _ingress_full_ms_samples.append((now, float(full_duration_ms)))


def record_preprocessor_dropped() -> None:
    _rollover_if_needed()
    _state["preprocessor_dropped"] += 1


def record_chatter_overload_dropped() -> None:
    _rollover_if_needed()
    _state["chatter_overload_dropped"] += 1


def record_chatter_overload_degraded() -> None:
    _rollover_if_needed()
    _state["chatter_overload_degraded"] += 1


def record_stale_message_dropped() -> None:
    _rollover_if_needed()
    _state["stale_messages_dropped"] += 1


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


def _samples_within_window(samples: deque[tuple[float, float]]) -> list[float]:
    if not samples:
        return []
    cutoff = time.monotonic() - ingress_sample_window_sec()
    return [ms for ts, ms in samples if ts >= cutoff]


def _percentile(ms_values: list[float], ratio: float) -> float | None:
    if not ms_values:
        return None
    ordered = sorted(ms_values)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * ratio)))
    return round(float(ordered[idx]), 2)


def ingress_duration_p95_ms() -> float | None:
    """调度分发阶段（matcher 执行前）p95。"""
    return _percentile(_samples_within_window(_ingress_ms_samples), 0.95)


def ingress_full_duration_p95_ms() -> float | None:
    """全链路（含 matcher/handler 执行）p95。"""
    return _percentile(_samples_within_window(_ingress_full_ms_samples), 0.95)


def lane_wait_avg_ms() -> float | None:
    count = int(_state["lane_wait_count"])
    if count <= 0:
        return None
    return round(float(_state["lane_wait_ms_total"]) / count, 2)


def dispatch_alerts(
    *, p95_ms: float | None, pg_util: float | None, work_aux: dict[str, Any] | None = None
) -> list[str]:
    alerts: list[str] = []
    if p95_ms is not None:
        if p95_ms > 5_000.0:
            alerts.append("ingress_p95_over_5000ms")
        elif p95_ms > 1_000.0:
            alerts.append("ingress_p95_over_1000ms")
    if pg_util is not None and pg_util >= 0.85:
        alerts.append("pg_pool_over_85pct")
    work = work_aux or {}
    if work.get("available") and float(work.get("heartbeat_age_sec") or 0) > 15.0:
        alerts.append("work_aux_heartbeat_stale")
    if float(work.get("oldest_pending_age_sec") or 0) > 300.0:
        alerts.append("work_aux_backlog_old")
    return alerts


def dispatch_metrics_snapshot() -> dict[str, Any]:
    _rollover_if_needed()
    from pallas.core.foundation.db.pool_budget import pool_budget_status
    from pallas.core.platform.ingress.conversation_scheduler import conversation_scheduler_status
    from pallas.core.platform.ingress.dispatch_lanes import lane_status
    from pallas.core.platform.ingress.hotpath_metrics import hotpath_metrics_snapshot
    from pallas.core.platform.ingress.send_queue import send_queue_status
    from pallas.core.platform.work_jobs.observability import work_aux_status

    p95 = ingress_duration_p95_ms()
    full_p95 = ingress_full_duration_p95_ms()
    pool = pool_budget_status()
    pg_util = pool.get("utilization")
    counters = {key: int(_state[key]) for key in _COUNTERS}
    return build_dispatch_metrics_payload(
        day_key=_day_key or _today_key(),
        counters=counters,
        ingress_duration_ms_p95=p95,
        ingress_full_ms_p95=full_p95,
        send_queue=send_queue_status(),
        pool_budget=pool,
        pg_util=pg_util if isinstance(pg_util, float) else None,
        hotpath=hotpath_metrics_snapshot(),
        work_aux=work_aux_status(),
        conversation_scheduler=conversation_scheduler_status(),
        lanes=lane_status(),
        snapshot_health=ingress_snapshot_health(),
        route_candidates=route_candidate_metrics_snapshot(),
    )


def build_dispatch_metrics_payload(
    *,
    day_key: str,
    counters: dict[str, int],
    ingress_duration_ms_p95: float | None,
    ingress_full_ms_p95: float | None = None,
    send_queue: dict[str, Any],
    pool_budget: dict[str, Any],
    pg_util: float | None,
    hotpath: dict[str, Any] | None = None,
    work_aux: dict[str, Any] | None = None,
    conversation_scheduler: dict[str, Any] | None = None,
    lanes: dict[str, dict[str, int]] | None = None,
    snapshot_health: dict[str, Any] | None = None,
    route_candidates: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    group_messages = int(counters.get("group_messages") or 0)
    command_traffic = int(counters.get("command_traffic") or 0)
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
        "ingress_full_ms_p95": ingress_full_ms_p95,
        "send_queue": send_queue,
        "pool_budget": pool_budget,
        "hotpath": hotpath or {},
        "work_aux": work_aux or {},
        "conversation_scheduler": conversation_scheduler or {},
        "lanes": lanes or {},
        "snapshot_health": snapshot_health or {},
        "route_candidates": route_candidates or [],
        "alerts": dispatch_alerts(p95_ms=ingress_duration_ms_p95, pg_util=pg_util, work_aux=work_aux),
        "matchers_selected_ratio": round(selected / considered, 4) if considered else None,
        "avg_matchers_per_message": round(selected / group_messages, 2) if group_messages else None,
        # 命令才走 route index；闲聊 hit=0 是常态，勿除以全部群消息
        "route_index_hit_ratio": round(route_hits / command_traffic, 4) if command_traffic else None,
        "route_index_fallback_ratio": round(route_fallbacks / command_traffic, 4) if command_traffic else None,
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


def merge_conversation_scheduler_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "enabled": False,
        "concurrency": 0,
        "pending": 0,
        "active": 0,
        "ready": 0,
        "max_pending": 0,
        "per_key_pending_limit": 0,
        "active_keys": 0,
        "wait_ms_p95": None,
        "run_ms_p95": None,
        "backpressure_waits": 0,
        "per_key_backpressure_waits": 0,
    }
    waits: list[float] = []
    runs: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        merged["enabled"] = bool(merged["enabled"] or row.get("enabled"))
        for key in (
            "pending",
            "concurrency",
            "active",
            "ready",
            "max_pending",
            "per_key_pending_limit",
            "active_keys",
            "backpressure_waits",
            "per_key_backpressure_waits",
        ):
            merged[key] += int(row.get(key) or 0)
        wait = row.get("wait_ms_p95")
        if isinstance(wait, (int, float)):
            waits.append(float(wait))
        run = row.get("run_ms_p95")
        if isinstance(run, (int, float)):
            runs.append(float(run))
    if waits:
        merged["wait_ms_p95"] = round(max(waits), 2)
    if runs:
        merged["run_ms_p95"] = round(max(runs), 2)
    return merged


def merge_snapshot_health(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for name, status in row.items():
            if isinstance(status, dict):
                grouped.setdefault(str(name), []).append(status)

    merged: dict[str, dict[str, Any]] = {}
    for name, statuses in grouped.items():
        ready_workers = sum(1 for status in statuses if status.get("ready") is True)
        refresh_ages = [
            float(status["refresh_age_sec"])
            for status in statuses
            if isinstance(status.get("refresh_age_sec"), (int, float))
        ]
        failure_ages = [
            float(status["last_failure_age_sec"])
            for status in statuses
            if isinstance(status.get("last_failure_age_sec"), (int, float))
        ]
        merged[name] = {
            "ready": ready_workers == len(statuses),
            "workers": len(statuses),
            "ready_workers": ready_workers,
            "refresh_age_sec_max": round(max(refresh_ages), 2) if refresh_ages else None,
            "refresh_failures": sum(int(status.get("refresh_failures") or 0) for status in statuses),
            "last_failure_age_sec_min": round(min(failure_ages), 2) if failure_ages else None,
        }
    return merged


def merge_work_aux_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [row for row in rows if row.get("available") is True]
    if not available:
        return {"available": False}
    merged: dict[str, Any] = {"available": True}
    heartbeat_ages = [
        float(row["heartbeat_age_sec"]) for row in available if isinstance(row.get("heartbeat_age_sec"), (int, float))
    ]
    if heartbeat_ages:
        merged["heartbeat_age_sec"] = round(min(heartbeat_ages), 2)
    for key in ("consumers", "pending", "leased", "dead_lettered", "oldest_pending_age_sec", "max_attempts"):
        values = [float(row[key]) for row in available if isinstance(row.get(key), (int, float))]
        if values:
            value = max(values)
            merged[key] = int(value) if key != "oldest_pending_age_sec" else value
    return merged


def merge_dispatch_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dispatch_metrics_snapshot()
    counters = dict.fromkeys(_COUNTERS, 0)
    p95_values: list[float] = []
    full_p95_values: list[float] = []
    send_rows: list[dict[str, Any]] = []
    pool_rows: list[dict[str, Any]] = []
    hotpath_rows: list[dict[str, Any]] = []
    work_aux_rows: list[dict[str, Any]] = []
    scheduler_rows: list[dict[str, Any]] = []
    snapshot_health_rows: list[dict[str, Any]] = []
    route_candidate_rows: list[list[dict[str, object]]] = []
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
        full_p95 = row.get("ingress_full_ms_p95")
        if isinstance(full_p95, (int, float)):
            full_p95_values.append(float(full_p95))
        send = row.get("send_queue")
        if isinstance(send, dict):
            send_rows.append(send)
        pool = row.get("pool_budget")
        if isinstance(pool, dict):
            pool_rows.append(pool)
        hotpath = row.get("hotpath")
        if isinstance(hotpath, dict):
            hotpath_rows.append(hotpath)
        work_aux = row.get("work_aux")
        if isinstance(work_aux, dict):
            work_aux_rows.append(work_aux)
        scheduler = row.get("conversation_scheduler")
        if isinstance(scheduler, dict):
            scheduler_rows.append(scheduler)
        snapshot_health = row.get("snapshot_health")
        if isinstance(snapshot_health, dict):
            snapshot_health_rows.append(snapshot_health)
        route_candidates = row.get("route_candidates")
        if isinstance(route_candidates, list):
            route_candidate_rows.append(route_candidates)
    p95_cluster = round(max(p95_values), 2) if p95_values else None
    full_p95_cluster = round(max(full_p95_values), 2) if full_p95_values else None
    pool_merged = merge_pool_budget_snapshots(pool_rows)
    pg_util = pool_merged.get("utilization")
    from pallas.core.platform.ingress.hotpath_metrics import merge_hotpath_metrics

    return build_dispatch_metrics_payload(
        day_key=day_key or _today_key(),
        counters=counters,
        ingress_duration_ms_p95=p95_cluster,
        ingress_full_ms_p95=full_p95_cluster,
        send_queue=merge_send_queue_snapshots(send_rows),
        pool_budget=pool_merged,
        pg_util=pg_util if isinstance(pg_util, float) else None,
        hotpath=merge_hotpath_metrics(hotpath_rows),
        work_aux=merge_work_aux_snapshots(work_aux_rows),
        conversation_scheduler=merge_conversation_scheduler_snapshots(scheduler_rows),
        snapshot_health=merge_snapshot_health(snapshot_health_rows),
        route_candidates=merge_route_candidate_snapshots(route_candidate_rows),
    )


def merge_route_candidate_snapshots(rows: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    counter_keys = (
        "messages",
        "route_index_hits",
        "route_index_fallbacks",
        "matchers_considered",
        "matchers_selected",
        "matchers_run",
        "direct_handled",
        "direct_fallback",
        "direct_error",
        "matcher_handled",
        "direct_visible_actions",
        "direct_effect_actions",
    )
    merged: dict[tuple[str, ...], dict[str, object]] = {}
    for snapshot in rows:
        for raw in snapshot:
            if not isinstance(raw, dict):
                continue
            modules_raw = raw.get("route_modules")
            if not isinstance(modules_raw, list):
                continue
            route = tuple(sorted({str(module).strip() for module in modules_raw if str(module).strip()}))
            if route not in merged and route and len([key for key in merged if key]) >= 64:
                route = ()
            target = merged.setdefault(route, {"route_modules": list(route), **dict.fromkeys(counter_keys, 0)})
            for key in counter_keys:
                historical_key = {
                    "direct_handled": "native_handled",
                    "direct_fallback": "native_fallback",
                    "direct_error": "native_error",
                    "matcher_handled": "legacy_handled",
                    "direct_visible_actions": "native_visible_actions",
                    "direct_effect_actions": "native_effect_actions",
                }.get(key)
                value = (
                    int(raw.get(key) or 0) + int(raw.get(historical_key) or 0)
                    if historical_key
                    else int(raw.get(key) or 0)
                )
                target[key] = int(target[key]) + max(0, value)
            p95 = raw.get("ingress_duration_ms_p95")
            if isinstance(p95, (int, float)) and not isinstance(p95, bool):
                target["ingress_duration_ms_p95"] = max(
                    float(target.get("ingress_duration_ms_p95") or 0.0),
                    max(0.0, float(p95)),
                )
            full_p95 = raw.get("ingress_full_ms_p95")
            if isinstance(full_p95, (int, float)) and not isinstance(full_p95, bool):
                target["ingress_full_ms_p95"] = max(
                    float(target.get("ingress_full_ms_p95") or 0.0),
                    max(0.0, float(full_p95)),
                )
    result = list(merged.values())
    for row in result:
        messages = int(row["messages"])
        row.setdefault("ingress_duration_ms_p95", None)
        row.setdefault("ingress_full_ms_p95", None)
        row["eligible"] = (
            len(row["route_modules"]) == 1
            and int(row["matcher_handled"]) > 0
            and int(row["route_index_fallbacks"]) == 0
            and int(row["direct_error"]) == 0
            and int(row["direct_handled"]) < messages
        )
    result.sort(key=lambda row: tuple(row["route_modules"]))
    return result
