"""入站/接话热路径埋点：阶段耗时样本 + 缓存/查库/学习结果计数。

挂在 ``dispatch_metrics_snapshot()["hotpath"]``，供跑一天对照：
路由/分词是否还贵、bundle 是否吃 PG、learn 是否在让路。
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
)
_state: dict[str, int] = dict.fromkeys(_COUNTERS, 0)
_day_key = ""
_SAMPLE_MAX = 512
_route_ms: deque[float] = deque(maxlen=_SAMPLE_MAX)
_keywords_ms: deque[float] = deque(maxlen=_SAMPLE_MAX)
_bundle_ms: deque[float] = deque(maxlen=_SAMPLE_MAX)


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


def clear_hotpath_metrics_for_tests() -> None:
    global _day_key
    _day_key = ""
    for key in _COUNTERS:
        _state[key] = 0
    _route_ms.clear()
    _keywords_ms.clear()
    _bundle_ms.clear()


def _percentile(samples: deque[float], ratio: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * ratio)))
    return round(float(ordered[idx]), 3)


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


def hotpath_metrics_snapshot() -> dict[str, Any]:
    _rollover_if_needed()
    bundle_lookups = int(_state["bundle_lookup_calls"])
    cache_hits = int(_state["bundle_cache_hit"]) + int(_state["bundle_cache_negative_hit"])
    return {
        "day_key": _day_key or _today_key(),
        **{key: int(_state[key]) for key in _COUNTERS},
        "route_ms_p50": _percentile(_route_ms, 0.50),
        "route_ms_p95": _percentile(_route_ms, 0.95),
        "keywords_ms_p50": _percentile(_keywords_ms, 0.50),
        "keywords_ms_p95": _percentile(_keywords_ms, 0.95),
        "bundle_ms_p50": _percentile(_bundle_ms, 0.50),
        "bundle_ms_p95": _percentile(_bundle_ms, 0.95),
        "bundle_cache_hit_ratio": round(cache_hits / bundle_lookups, 4) if bundle_lookups else None,
        **_keywords_cache_stats(),
    }


def merge_hotpath_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return hotpath_metrics_snapshot()
    counters = dict.fromkeys(_COUNTERS, 0)
    day_key = ""
    p95_route: list[float] = []
    p95_kw: list[float] = []
    p95_bundle: list[float] = []
    p50_route: list[float] = []
    p50_kw: list[float] = []
    p50_bundle: list[float] = []
    lru_hits = 0
    lru_misses = 0
    lru_size = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        for key in _COUNTERS:
            counters[key] += int(row.get(key) or 0)
        for dest, src in (
            (p95_route, "route_ms_p95"),
            (p95_kw, "keywords_ms_p95"),
            (p95_bundle, "bundle_ms_p95"),
            (p50_route, "route_ms_p50"),
            (p50_kw, "keywords_ms_p50"),
            (p50_bundle, "bundle_ms_p50"),
        ):
            val = row.get(src)
            if isinstance(val, (int, float)):
                dest.append(float(val))
        lru_hits += int(row.get("keywords_lru_hits") or 0)
        lru_misses += int(row.get("keywords_lru_misses") or 0)
        lru_size = max(lru_size, int(row.get("keywords_lru_size") or 0))
    lookups = int(counters["bundle_lookup_calls"])
    cache_hits = int(counters["bundle_cache_hit"]) + int(counters.get("bundle_cache_negative_hit") or 0)
    lru_total = lru_hits + lru_misses
    return {
        "day_key": day_key or _today_key(),
        **counters,
        "route_ms_p50": round(max(p50_route), 3) if p50_route else None,
        "route_ms_p95": round(max(p95_route), 3) if p95_route else None,
        "keywords_ms_p50": round(max(p50_kw), 3) if p50_kw else None,
        "keywords_ms_p95": round(max(p95_kw), 3) if p95_kw else None,
        "bundle_ms_p50": round(max(p50_bundle), 3) if p50_bundle else None,
        "bundle_ms_p95": round(max(p95_bundle), 3) if p95_bundle else None,
        "bundle_cache_hit_ratio": round(cache_hits / lookups, 4) if lookups else None,
        "keywords_lru_hits": lru_hits,
        "keywords_lru_misses": lru_misses,
        "keywords_lru_size": lru_size,
        "keywords_lru_hit_ratio": round(lru_hits / lru_total, 4) if lru_total else None,
    }
