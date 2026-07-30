"""LLM 任务计数：热路径仅内存自增，落盘由控制台定时任务异步完成。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

_STORE_VER = 1
_TASKS = frozenset({
    "llm_chat",
    "repeater_polish",
    "repeater_polish_lite",
    "repeater_fallback",
    "repeater_select",
    "affect_refine",
})
_EVENTS = frozenset({
    "submit_ok",
    "submit_skip",
    "callback_ok",
    "callback_fail",
    "reply_gate_skip",
    "reply_gate_defer",
    "reply_gate_proceed",
    "reply_gate_skip_face",
    "reply_gate_skip_noise",
    "reply_gate_skip_short",
    "reply_gate_skip_bystander",
    "reply_gate_skip_incomplete",
    "reply_gate_skip_shut_up",
    "speak_skip",
    "speak_mention",
    "speak_ambient",
    "speak_followup",
    "speak_skip_command",
    "speak_skip_bystander",
    "speak_skip_spam",
    "speak_skip_noise",
    "speak_skip_ambient",
    "selective_hit",
    "selective_empty",
    "soft_recall_hit",
    "soft_recall_empty",
    "soft_recall_ask_no_call",
    "inventory_hit",
    "tools_find_call",
    "tool_activate",
    "tool_call_ok",
    "tool_call_fail",
    "tool_session_called",
    "tool_session_no_call",
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
_hydrated = False
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


def _counters_from_snapshot(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    by_task = raw.get("by_task") if isinstance(raw.get("by_task"), dict) else {}
    for task, metrics in by_task.items():
        task_key = str(task or "").strip() or "other"
        if not isinstance(metrics, dict):
            continue
        for metric in _EVENTS:
            count = int(metrics.get(metric) or 0)
            if count > 0:
                out[f"{task_key}:{metric}"] = count
        route_counts = metrics.get("route_counts")
        if isinstance(route_counts, dict):
            for route, count in route_counts.items():
                c = int(count or 0)
                if c <= 0:
                    continue
                route_key = normalize_llm_route_name(str(route))
                out[f"route:{task_key}:{route_key}"] = c
    if out:
        return out
    # 兼容仅有 totals 的旧快照
    totals = raw.get("totals") if isinstance(raw.get("totals"), dict) else {}
    for metric in _EVENTS:
        count = int(totals.get(metric) or 0)
        if count > 0:
            out[f"llm_chat:{metric}"] = count
    return out


def _hydrate_from_disk_locked() -> None:
    global _hydrated  # noqa: PLW0603
    if _hydrated:
        return
    _hydrated = True
    today = str(_day_key or today_key()).strip()[:10]

    def apply_raw(raw: dict[str, Any]) -> None:
        if _counters:
            return
        loaded = _counters_from_snapshot(raw)
        if loaded:
            _counters.update(loaded)

    try:
        from pallas.product.llm.shard_metric_hydrate import (
            allow_shared_stats_file_hydrate,
            load_worker_day_metric,
        )

        worker_raw = load_worker_day_metric(metric_key="llm_task", day_key=today)
        if isinstance(worker_raw, dict):
            apply_raw(worker_raw)
            return
        if not allow_shared_stats_file_hydrate():
            return
    except Exception:
        pass

    path = stats_file_path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict) or not raw.get("day_key"):
        return
    file_day = str(raw.get("day_key") or "").strip()[:10]
    if file_day and file_day != today:
        try:
            from pallas.product.llm.llm_daily_stats_store import write_day_side

            write_day_side(file_day, "bot", {**raw, "day_key": file_day, "source": "bot"})
        except Exception:
            pass
        return
    apply_raw(raw)


def rollover_if_needed() -> None:
    global _day_key, _hydrated  # noqa: PLW0603
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
        _counters.clear()
        _day_key = today
        _hydrated = True
        return
    _day_key = today
    _hydrated = False


def record_bot_llm_task(task: str | None, event: str) -> None:
    if event not in _EVENTS:
        return
    key = normalize_llm_task_name(task)
    try:
        with _lock:
            rollover_if_needed()
            _hydrate_from_disk_locked()
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
            _hydrate_from_disk_locked()
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
        _hydrate_from_disk_locked()
        return snapshot_locked()


def flush_stats_sync() -> None:
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_worker():
            return
        # 只落盘本进程，禁止写 cluster 合计，否则 hub hydrate 后再合并 worker 会翻倍
        snapshot = llm_task_metrics_snapshot()
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

        # 日汇总仍可用 cluster（读路径），此处写本进程；完整集群由 fetch 时 merge 写入
        write_day_side(str(snapshot.get("day_key") or today_key()), "bot", snapshot)
    except Exception:
        pass


def clear_llm_task_metrics_for_tests() -> None:
    global _day_key, _hydrated  # noqa: PLW0603
    with _lock:
        _day_key = today_key()
        _hydrated = True
        _counters.clear()
