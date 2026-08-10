from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

_MAX_NAMED_ROUTES = 64
_OTHER_ROUTE: tuple[str, ...] = ()
_NATIVE_OUTCOMES = ("native_handled", "native_fallback", "native_error")


@dataclass(slots=True)
class RouteCandidateMetrics:
    messages: int = 0
    route_index_hits: int = 0
    route_index_fallbacks: int = 0
    matchers_considered: int = 0
    matchers_selected: int = 0
    matchers_run: int = 0
    native_handled: int = 0
    native_fallback: int = 0
    native_error: int = 0
    legacy_handled: int = 0
    native_visible_actions: int = 0
    native_effect_actions: int = 0
    durations_ms: deque[float] = field(default_factory=lambda: deque(maxlen=256))


_day_key = ""
_routes: dict[tuple[str, ...], RouteCandidateMetrics] = {}


def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def rollover_if_needed() -> None:
    global _day_key
    today = today_key()
    if _day_key == today:
        return
    _day_key = today
    _routes.clear()


def clear_route_candidate_metrics_for_tests() -> None:
    global _day_key
    _day_key = ""
    _routes.clear()


def normalized_route_key(route_modules: frozenset[str]) -> tuple[str, ...]:
    route = tuple(sorted(module.strip() for module in route_modules if module.strip()))
    if not route:
        return _OTHER_ROUTE
    if route in _routes or len([key for key in _routes if key]) < _MAX_NAMED_ROUTES:
        return route
    return _OTHER_ROUTE


def record_route_candidate(
    *,
    route_modules: frozenset[str],
    index_hit: bool,
    route_fallback: bool,
    matchers_considered: int,
    matchers_selected: int,
    matchers_run: int,
    native_outcome: str | None,
    legacy_handled: bool,
    native_visible_actions: int | None,
    native_effect_actions: int | None,
    duration_ms: float,
) -> None:
    rollover_if_needed()
    route = normalized_route_key(route_modules)
    row = _routes.setdefault(route, RouteCandidateMetrics())
    row.messages += 1
    row.route_index_hits += int(index_hit)
    row.route_index_fallbacks += int(route_fallback)
    row.matchers_considered += max(0, matchers_considered)
    row.matchers_selected += max(0, matchers_selected)
    row.matchers_run += max(0, matchers_run)
    if native_outcome in _NATIVE_OUTCOMES:
        setattr(row, native_outcome, getattr(row, native_outcome) + 1)
    row.legacy_handled += int(legacy_handled)
    if native_visible_actions is not None:
        row.native_visible_actions += max(0, native_visible_actions)
    if native_effect_actions is not None:
        row.native_effect_actions += max(0, native_effect_actions)
    if duration_ms >= 0:
        row.durations_ms.append(float(duration_ms))


def duration_p95(samples: deque[float]) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95)))
    return round(float(ordered[index]), 2)


def route_candidate_metrics_snapshot() -> list[dict[str, object]]:
    rollover_if_needed()
    rows: list[dict[str, object]] = []
    for route, metrics in _routes.items():
        p95 = duration_p95(metrics.durations_ms)
        rows.append({
            "route_modules": list(route),
            "messages": metrics.messages,
            "route_index_hits": metrics.route_index_hits,
            "route_index_fallbacks": metrics.route_index_fallbacks,
            "matchers_considered": metrics.matchers_considered,
            "matchers_selected": metrics.matchers_selected,
            "matchers_run": metrics.matchers_run,
            "native_handled": metrics.native_handled,
            "native_fallback": metrics.native_fallback,
            "native_error": metrics.native_error,
            "legacy_handled": metrics.legacy_handled,
            "native_visible_actions": metrics.native_visible_actions,
            "native_effect_actions": metrics.native_effect_actions,
            "ingress_duration_ms_p95": p95,
            "eligible": (
                len(route) == 1
                and metrics.legacy_handled > 0
                and metrics.route_index_fallbacks == 0
                and metrics.native_error == 0
                and metrics.native_handled < metrics.messages
            ),
        })
    rows.sort(
        key=lambda row: (
            -int(row["legacy_handled"]),
            -int(row["matchers_selected"]),
            -int(row["matchers_run"]),
            -float(row["ingress_duration_ms_p95"] or 0.0),
            tuple(row["route_modules"]),
        )
    )
    return rows
