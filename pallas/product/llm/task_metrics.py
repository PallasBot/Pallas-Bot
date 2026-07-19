"""LLM 任务计数：热路径仅内存自增，落盘由控制台定时任务异步完成。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

_STORE_VER = 1
_TASKS = frozenset({"llm_chat", "repeater_polish", "repeater_polish_lite", "repeater_fallback", "repeater_select"})
_EVENTS = frozenset({
    "submit_ok",
    "submit_skip",
    "callback_ok",
    "callback_fail",
    "reply_gate_skip",
    "reply_gate_defer",
})
_ROUTE_BUCKETS = frozenset({
    "plain_llm_chat",
    "corpus_select",
    "corpus_polish_lite",
    "corpus_polish",
    "corpus_fallback",
    "pipeline_select",
    "pipeline_rewrite",
    "pipeline_stitch",
    "pipeline_generate",
})

_lock = threading.Lock()
_day_key = ""
_counters: dict[str, int] = {}


def normalize_llm_task_name(raw: str | None) -> str:
    task = str(raw or "").strip().lower()
    if task in _TASKS:
        return task
    if task:
        return "other"
    return "llm_chat"


def stats_file_path():
    data_dir = plugin_data_dir("pb_webui", create=True)
    return data_dir / "llm_task_stats.json"


def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def snapshot_locked(*, day_override: str | None = None) -> dict[str, Any]:
    by_task: dict[str, dict[str, int]] = {}
    totals = dict.fromkeys(_EVENTS, 0)
    for compound, value in _counters.items():
        if compound.startswith("route:"):
            _, task, route = compound.split(":", 2)
            row = by_task.setdefault(task, dict.fromkeys(_EVENTS, 0))
            route_counts = row.setdefault("route_counts", {})
            route_counts[route] = int(value)
            continue
        if ":" not in compound:
            continue
        task, metric = compound.split(":", 1)
        if metric not in _EVENTS:
            continue
        row = by_task.setdefault(task, dict.fromkeys(_EVENTS, 0))
        count = int(value)
        row[metric] = count
        totals[metric] += count
    return {
        "source": "bot",
        "day_key": day_override or _day_key or today_key(),
        "updated_at": time.time(),
        "by_task": by_task,
        "totals": totals,
    }


def rollover_if_needed() -> None:
    global _day_key  # noqa: PLW0603
    today = today_key()
    if _day_key == today:
        return
    if _day_key:
        try:
            from pallas.product.llm.llm_daily_stats_store import write_day_side

            old_snapshot = snapshot_locked(day_override=_day_key)
            write_day_side(_day_key, "bot", old_snapshot)
        except Exception:
            pass
    _day_key = today
    _counters.clear()


def record_bot_llm_task(task: str | None, event: str) -> None:
    if event not in _EVENTS:
        return
    key = normalize_llm_task_name(task)
    try:
        with _lock:
            rollover_if_needed()
            _counters[f"{key}:{event}"] = int(_counters.get(f"{key}:{event}", 0)) + 1
    except Exception:
        pass


def normalize_llm_route_name(raw: str | None) -> str:
    route = str(raw or "").strip().lower()
    if route in _ROUTE_BUCKETS:
        return route
    return "plain_llm_chat"


def record_bot_llm_route(task: str | None, route: str | None) -> None:
    key = normalize_llm_task_name(task)
    route_key = normalize_llm_route_name(route)
    try:
        with _lock:
            rollover_if_needed()
            compound = f"route:{key}:{route_key}"
            _counters[compound] = int(_counters.get(compound, 0)) + 1
    except Exception:
        pass


def merge_llm_task_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, int]] = {}
    totals = dict.fromkeys(_EVENTS, 0)
    day_key = ""
    updated_at = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        try:
            updated_at = max(updated_at, float(row.get("updated_at") or 0))
        except (TypeError, ValueError):
            pass
        src_by_task = row.get("by_task")
        if isinstance(src_by_task, dict):
            for task, metrics in src_by_task.items():
                task_key = str(task).strip() or "other"
                dst = by_task.setdefault(task_key, dict.fromkeys(_EVENTS, 0))
                if not isinstance(metrics, dict):
                    continue
                for metric in _EVENTS:
                    dst[metric] += int(metrics.get(metric) or 0)
                route_counts = metrics.get("route_counts")
                if isinstance(route_counts, dict):
                    dst_route_counts = dst.setdefault("route_counts", {})
                    for route, count in route_counts.items():
                        route_key = normalize_llm_route_name(str(route))
                        dst_route_counts[route_key] = int(dst_route_counts.get(route_key, 0)) + int(count or 0)
        src_totals = row.get("totals")
        if isinstance(src_totals, dict):
            for metric in _EVENTS:
                totals[metric] += int(src_totals.get(metric) or 0)
    if not totals or not any(totals.values()):
        for metrics in by_task.values():
            for metric in _EVENTS:
                totals[metric] += int(metrics.get(metric) or 0)
    return {
        "source": "bot_cluster",
        "day_key": day_key or today_key(),
        "updated_at": updated_at or time.time(),
        "by_task": by_task,
        "totals": totals,
    }


def cluster_llm_task_metrics_snapshot(*, max_stale_sec: float = 300.0) -> dict[str, Any]:
    """分片 hub：合并本进程与各 worker stats 中的 llm_task 快照。"""
    rows = [llm_task_metrics_snapshot()]
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            from pallas.core.platform.shard.console_stats import iter_worker_shard_ids, read_worker_stats_file

            for shard_id in iter_worker_shard_ids(max_stale_sec=max_stale_sec):
                blob = read_worker_stats_file(shard_id)
                llm = blob.get("llm_task")
                if not isinstance(llm, dict):
                    continue
                if not llm.get("by_task") and not any((llm.get("totals") or {}).values()):
                    continue
                rows.append(llm)
    except Exception:
        pass
    if len(rows) <= 1:
        return rows[0]
    return merge_llm_task_snapshots(rows)


def llm_task_metrics_snapshot() -> dict[str, Any]:
    with _lock:
        rollover_if_needed()
        return snapshot_locked()


def flush_stats_sync() -> None:
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_worker():
            return
        snapshot = (
            cluster_llm_task_metrics_snapshot()
            if shard_ctx.sharding_active() and shard_ctx.is_hub()
            else llm_task_metrics_snapshot()
        )
    except Exception:
        snapshot = llm_task_metrics_snapshot()
    if not snapshot.get("by_task") and not any(snapshot.get("totals", {}).values()):
        return
    path = stats_file_path()
    payload = {"v": _STORE_VER, **snapshot}
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    try:
        from pallas.product.llm.llm_daily_stats_store import write_day_side

        write_day_side(str(snapshot.get("day_key") or today_key()), "bot", snapshot)
    except Exception:
        pass


def clear_llm_task_metrics_for_tests() -> None:
    global _day_key  # noqa: PLW0603
    with _lock:
        _day_key = ""
        _counters.clear()
