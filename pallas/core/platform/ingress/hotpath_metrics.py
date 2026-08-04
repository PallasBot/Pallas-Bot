"""入站/接话热路径埋点：阶段耗时样本 + 缓存/查库/学习结果计数。

挂在 ``dispatch_metrics_snapshot()["hotpath"]``，供跑一天对照：
路由/分词是否还贵、bundle 是否吃 PG、learn 是否在让路。

bundle 阶段拆分（``record_bundle_stages`` / 查库子阶段）用于定位 P95：
db_find / persona / affect / ban / feedback / select，以及 snapshot 命中与 SQL 分段。
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

_COUNTERS = (
    "route_resolve_calls",
    "keywords_extract_calls",
    "bundle_lookup_calls",
    "bundle_cache_hit",
    "bundle_cache_negative_hit",
    "bundle_cache_miss",
    "bundle_found",
    "bundle_none",
    "bundle_timeout",
    "bundle_db_error",
    "bundle_other_error",
    "learn_enqueued",
    "learn_skipped_pressure",
    "learn_skipped_full",
    "learn_completed",
    "chat_shed_sidework",
    "reply_local_dispatched",
    "llm_path_skipped_shed",
    "llm_retained_under_shed",
    "bundle_stage_db_miss",
    "bundle_stage_db_hit",
    "bundle_stage_no_candidates",
    "bundle_stage_found",
    "reply_snapshot_hit",
    "reply_snapshot_miss",
    "reply_snapshot_skip",
    "reply_query_uncached",
)
_STAGE_KEYS = (
    "db_find",
    "persona",
    "affect",
    "ban",
    "feedback",
    "select",
    "sql_context",
    "sql_ban",
    "sql_answer",
    "sql_message",
    "sql_total",
)
_state: dict[str, int] = dict.fromkeys(_COUNTERS, 0)
_day_key = ""
_SAMPLE_MAX = 512
_route_ms: deque[float] = deque(maxlen=_SAMPLE_MAX)
_keywords_ms: deque[float] = deque(maxlen=_SAMPLE_MAX)
_bundle_ms: deque[float] = deque(maxlen=_SAMPLE_MAX)
_stage_ms: dict[str, deque[float]] = {key: deque(maxlen=_SAMPLE_MAX) for key in _STAGE_KEYS}


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
    _route_ms.clear()
    _keywords_ms.clear()
    _bundle_ms.clear()
    for samples in _stage_ms.values():
        samples.clear()


def clear_hotpath_metrics_for_tests() -> None:
    global _day_key
    _day_key = ""
    for key in _COUNTERS:
        _state[key] = 0
    _route_ms.clear()
    _keywords_ms.clear()
    _bundle_ms.clear()
    for samples in _stage_ms.values():
        samples.clear()


def _percentile(samples: deque[float], ratio: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * ratio)))
    return round(float(ordered[idx]), 3)


def _append_stage(name: str, duration_ms: float | None) -> None:
    if duration_ms is None or duration_ms < 0:
        return
    samples = _stage_ms.get(name)
    if samples is None:
        return
    samples.append(float(duration_ms))


def record_route_resolve_ms(duration_ms: float) -> None:
    _rollover_if_needed()
    _state["route_resolve_calls"] += 1
    if duration_ms >= 0:
        _route_ms.append(float(duration_ms))


def record_keywords_extract_ms(duration_ms: float) -> None:
    _rollover_if_needed()
    _state["keywords_extract_calls"] += 1
    if duration_ms >= 0:
        _keywords_ms.append(float(duration_ms))


def record_bundle_lookup(
    *,
    duration_ms: float,
    cache_hit: bool,
    found: bool | None = None,
    error: str | None = None,
    negative_hit: bool = False,
) -> None:
    _rollover_if_needed()
    _state["bundle_lookup_calls"] += 1
    if duration_ms >= 0:
        _bundle_ms.append(float(duration_ms))
    if cache_hit:
        if negative_hit:
            _state["bundle_cache_negative_hit"] += 1
            _state["bundle_none"] += 1
        else:
            _state["bundle_cache_hit"] += 1
            if found:
                _state["bundle_found"] += 1
        return
    _state["bundle_cache_miss"] += 1
    if error == "timeout":
        _state["bundle_timeout"] += 1
        return
    if error == "db_timeout":
        _state["bundle_db_error"] += 1
        return
    if error:
        _state["bundle_other_error"] += 1
        return
    if found:
        _state["bundle_found"] += 1
    else:
        _state["bundle_none"] += 1


def record_bundle_stages(
    *,
    outcome: str,
    db_find_ms: float | None = None,
    persona_ms: float | None = None,
    affect_ms: float | None = None,
    ban_ms: float | None = None,
    feedback_ms: float | None = None,
    select_ms: float | None = None,
) -> None:
    """``find_reply_bundle`` 内部阶段；outcome: db_miss / no_candidates / found。"""
    _rollover_if_needed()
    if outcome == "db_miss":
        _state["bundle_stage_db_miss"] += 1
    elif outcome == "no_candidates":
        _state["bundle_stage_db_hit"] += 1
        _state["bundle_stage_no_candidates"] += 1
    elif outcome == "found":
        _state["bundle_stage_db_hit"] += 1
        _state["bundle_stage_found"] += 1
    _append_stage("db_find", db_find_ms)
    _append_stage("persona", persona_ms)
    _append_stage("affect", affect_ms)
    _append_stage("ban", ban_ms)
    _append_stage("feedback", feedback_ms)
    _append_stage("select", select_ms)


def record_reply_snapshot(*, hit: bool, skipped: bool = False) -> None:
    _rollover_if_needed()
    if skipped:
        _state["reply_snapshot_skip"] += 1
        return
    if hit:
        _state["reply_snapshot_hit"] += 1
    else:
        _state["reply_snapshot_miss"] += 1


def record_reply_query_stages(
    *,
    context_ms: float,
    ban_ms: float,
    answer_ms: float,
    message_ms: float,
    total_ms: float,
) -> None:
    """未走 snapshot 缓存时的 SQL 分段（每次 uncached loader）。"""
    _rollover_if_needed()
    _state["reply_query_uncached"] += 1
    _append_stage("sql_context", context_ms)
    _append_stage("sql_ban", ban_ms)
    _append_stage("sql_answer", answer_ms)
    _append_stage("sql_message", message_ms)
    _append_stage("sql_total", total_ms)


def record_learn_enqueued() -> None:
    _rollover_if_needed()
    _state["learn_enqueued"] += 1


def record_learn_skipped_pressure() -> None:
    _rollover_if_needed()
    _state["learn_skipped_pressure"] += 1


def record_learn_skipped_full() -> None:
    _rollover_if_needed()
    _state["learn_skipped_full"] += 1


def record_learn_completed() -> None:
    _rollover_if_needed()
    _state["learn_completed"] += 1


def record_chat_shed_sidework() -> None:
    _rollover_if_needed()
    _state["chat_shed_sidework"] += 1


def record_reply_local_dispatched() -> None:
    _rollover_if_needed()
    _state["reply_local_dispatched"] += 1


def record_llm_path_skipped_shed() -> None:
    _rollover_if_needed()
    _state["llm_path_skipped_shed"] += 1


def record_llm_retained_under_shed() -> None:
    _rollover_if_needed()
    _state["llm_retained_under_shed"] += 1


def _keywords_cache_stats() -> dict[str, int | float | None]:
    try:
        from packages.repeater.model import extract_keyword_tags

        info = extract_keyword_tags.cache_info()
        hits = int(info.hits)
        misses = int(info.misses)
        total = hits + misses
        return {
            "keywords_lru_hits": hits,
            "keywords_lru_misses": misses,
            "keywords_lru_size": int(info.currsize),
            "keywords_lru_hit_ratio": round(hits / total, 4) if total else None,
        }
    except Exception:
        return {
            "keywords_lru_hits": 0,
            "keywords_lru_misses": 0,
            "keywords_lru_size": 0,
            "keywords_lru_hit_ratio": None,
        }


def _stage_percentiles() -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in _STAGE_KEYS:
        samples = _stage_ms[key]
        out[f"{key}_ms_p50"] = _percentile(samples, 0.50)
        out[f"{key}_ms_p95"] = _percentile(samples, 0.95)
    return out


def hotpath_metrics_snapshot() -> dict[str, Any]:
    _rollover_if_needed()
    bundle_lookups = int(_state["bundle_lookup_calls"])
    cache_hits = int(_state["bundle_cache_hit"]) + int(_state["bundle_cache_negative_hit"])
    snap_hit = int(_state["reply_snapshot_hit"])
    snap_miss = int(_state["reply_snapshot_miss"])
    snap_total = snap_hit + snap_miss
    try:
        from pallas.product.llm.execution_budget import llm_execution_budget_snapshot

        budget = llm_execution_budget_snapshot()
    except Exception:
        budget = {}
    return {
        "day_key": _day_key or _today_key(),
        **{key: int(_state[key]) for key in _COUNTERS},
        **budget,
        "route_ms_p50": _percentile(_route_ms, 0.50),
        "route_ms_p95": _percentile(_route_ms, 0.95),
        "keywords_ms_p50": _percentile(_keywords_ms, 0.50),
        "keywords_ms_p95": _percentile(_keywords_ms, 0.95),
        "bundle_ms_p50": _percentile(_bundle_ms, 0.50),
        "bundle_ms_p95": _percentile(_bundle_ms, 0.95),
        "bundle_cache_hit_ratio": round(cache_hits / bundle_lookups, 4) if bundle_lookups else None,
        "reply_snapshot_hit_ratio": round(snap_hit / snap_total, 4) if snap_total else None,
        **_stage_percentiles(),
        **_keywords_cache_stats(),
    }


def merge_hotpath_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return hotpath_metrics_snapshot()
    counters = dict.fromkeys(_COUNTERS, 0)
    day_key = ""
    percentile_keys = (
        "route_ms_p50",
        "route_ms_p95",
        "keywords_ms_p50",
        "keywords_ms_p95",
        "bundle_ms_p50",
        "bundle_ms_p95",
        *[f"{key}_ms_p50" for key in _STAGE_KEYS],
        *[f"{key}_ms_p95" for key in _STAGE_KEYS],
    )
    collected: dict[str, list[float]] = {key: [] for key in percentile_keys}
    lru_hits = 0
    lru_misses = 0
    lru_size = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        for key in _COUNTERS:
            counters[key] += int(row.get(key) or 0)
        for key in percentile_keys:
            val = row.get(key)
            if isinstance(val, (int, float)):
                collected[key].append(float(val))
        lru_hits += int(row.get("keywords_lru_hits") or 0)
        lru_misses += int(row.get("keywords_lru_misses") or 0)
        lru_size = max(lru_size, int(row.get("keywords_lru_size") or 0))
    lookups = int(counters["bundle_lookup_calls"])
    cache_hits = int(counters["bundle_cache_hit"]) + int(counters.get("bundle_cache_negative_hit") or 0)
    snap_hit = int(counters["reply_snapshot_hit"])
    snap_miss = int(counters["reply_snapshot_miss"])
    snap_total = snap_hit + snap_miss
    lru_total = lru_hits + lru_misses
    merged_pct = {key: (round(max(vals), 3) if vals else None) for key, vals in collected.items()}
    return {
        "day_key": day_key or _today_key(),
        **counters,
        **merged_pct,
        "bundle_cache_hit_ratio": round(cache_hits / lookups, 4) if lookups else None,
        "reply_snapshot_hit_ratio": round(snap_hit / snap_total, 4) if snap_total else None,
        "keywords_lru_hits": lru_hits,
        "keywords_lru_misses": lru_misses,
        "keywords_lru_size": lru_size,
        "keywords_lru_hit_ratio": round(lru_hits / lru_total, 4) if lru_total else None,
    }
