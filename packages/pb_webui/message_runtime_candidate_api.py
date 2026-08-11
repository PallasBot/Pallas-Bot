from __future__ import annotations

import copy
import math
import threading
import time
from typing import TYPE_CHECKING, Any

from pallas.core.platform.bot_runtime.plugin_matrix import (
    BUNDLED_PLAY_PLUGIN_NAMES,
    CORE_PLUGIN_NAMES,
    EXTRA_PLUGIN_NAMES,
)
from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package
from pallas.core.platform.message_runtime.candidate_ranking import rank_message_runtime_candidates

if TYPE_CHECKING:
    from fastapi import APIRouter

_PASSIVE_MODULES = frozenset({"repeater", "llm_chat", "greeting", "drink", "roulette"})
_PRIVATE_ONLY_MODULES = frozenset({"request_handler"})
_COMPLEX_REQUEST_MODULES = frozenset({"request_handler"})
_DIRECT_MODULES = frozenset({"drink", "greeting", "help", "llm_chat", "pb_core", "repeater", "roulette"})
_MATCHER_ONLY_MODULES = frozenset({"request_handler"})
_RISK_LABELS = {
    "roulette": ("stateful_side_effects", "privileged_side_effects"),
    "sing": ("remote_job_chain",),
    "arcana": ("third_party_plugin",),
}
_REPORT_LOCK = threading.Lock()
_REPORT_CACHE: dict[str, object] = {
    "day_key": "",
    "generated_at": 0,
    "route_window": {},
    "candidates": [],
    "data_quality": ["report_cache_cold"],
}


def dispatch_snapshot() -> dict[str, Any]:
    from pallas.core.platform.ingress.dispatch_metrics import dispatch_metrics_snapshot

    return dispatch_metrics_snapshot()


def plugin_stats_overview() -> dict[str, Any]:
    from .console_metrics_runtime import _plugin_run_stats_overview

    return _plugin_run_stats_overview(self_id=None, include_log_errors=False)


def route_history_snapshot() -> dict[str, Any]:
    from .ingress_metrics_history import route_candidate_history_snapshot

    return route_candidate_history_snapshot()


def aggregate_plugin_stats(overview: dict[str, Any]) -> list[dict[str, object]]:
    aggregated: dict[str, dict[str, object]] = {}
    bots = overview.get("bots")
    if not isinstance(bots, list):
        return []
    for bot in bots:
        if not isinstance(bot, dict) or not isinstance(bot.get("plugins"), list):
            continue
        for plugin in bot["plugins"]:
            if not isinstance(plugin, dict):
                continue
            module = canonical_plugin_package(str(plugin.get("name") or "").strip())
            if not module:
                continue
            row = aggregated.setdefault(
                module,
                {
                    "module": module,
                    "runs": 0,
                    "runs_today": 0,
                    "errors": 0,
                    "errors_today": 0,
                    "duration_ms_today": 0.0,
                },
            )
            runs_today = safe_int(plugin.get("runs_today"))
            row["runs"] = int(row["runs"]) + safe_int(plugin.get("runs"))
            row["runs_today"] = int(row["runs_today"]) + runs_today
            row["errors"] = int(row["errors"]) + safe_int(plugin.get("errors"))
            row["errors_today"] = int(row["errors_today"]) + safe_int(plugin.get("errors_today"))
            row["duration_ms_today"] = round(
                float(row["duration_ms_today"]) + runs_today * safe_float(plugin.get("avg_duration_ms_today")),
                2,
            )
    return list(aggregated.values())


def safe_float(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return max(0.0, float(value))
    return 0.0


def safe_int(value: object) -> int:
    return int(safe_float(value))


def build_message_runtime_candidate_report(*, ingress_snapshot: dict[str, Any] | None = None) -> dict[str, object]:
    generated_at = int(time.time())
    quality: set[str] = set()
    if ingress_snapshot is None:
        try:
            live = dispatch_snapshot()
        except Exception:  # noqa: BLE001
            live = {}
            quality.add("live_snapshot_unavailable")
    else:
        live = ingress_snapshot
    try:
        history = route_history_snapshot()
    except Exception:  # noqa: BLE001
        history = {}
        quality.add("route_history_unavailable")
    try:
        stats = aggregate_plugin_stats(plugin_stats_overview())
    except Exception:  # noqa: BLE001
        stats = []
        quality.add("plugin_stats_unavailable")

    live_day_key = str(live.get("day_key") or "")
    history_day_key = str(history.get("day_key") or "")
    day_key = live_day_key or history_day_key or time.strftime("%Y-%m-%d", time.localtime())
    history_matches_live = not live_day_key or live_day_key == history_day_key
    sharded = bool(live.get("sharded") or history.get("sharded"))
    if sharded:
        quality.add("sharded_route_totals_reset_sensitive")
    totals = history.get("today_totals")
    if not sharded and history_matches_live and isinstance(totals, list) and totals:
        route_candidates = totals
        route_source = "persisted_totals"
    else:
        live_candidates = live.get("route_candidates")
        route_candidates = live_candidates if isinstance(live_candidates, list) else []
        route_source = "live"
    if history.get("write_ok") is False:
        quality.add("route_history_write_failed")
    latest_at = history.get("latest_at")
    if isinstance(latest_at, int) and generated_at - latest_at > 45:
        quality.add("route_history_stale")
    route_window = {
        "retention_sec": int(history.get("retention_sec") or 0),
        "latest_at": latest_at,
        "source": route_source,
    }
    report = rank_message_runtime_candidates(
        plugin_stats=stats,
        route_candidates=route_candidates,
        passive_modules=_PASSIVE_MODULES,
        private_only_modules=_PRIVATE_ONLY_MODULES,
        complex_request_modules=_COMPLEX_REQUEST_MODULES,
        risk_labels_by_module=_RISK_LABELS,
        built_in_modules=CORE_PLUGIN_NAMES | BUNDLED_PLAY_PLUGIN_NAMES,
        official_extension_modules=EXTRA_PLUGIN_NAMES,
        direct_modules=_DIRECT_MODULES,
        matcher_only_modules=_MATCHER_ONLY_MODULES,
        day_key=day_key,
        generated_at=generated_at,
        route_window=route_window,
    )
    report["data_quality"] = sorted(set(report["data_quality"]) | quality)
    return report


def refresh_message_runtime_candidate_report(*, ingress_snapshot: dict[str, Any] | None = None) -> dict[str, object]:
    global _REPORT_CACHE
    report = build_message_runtime_candidate_report(ingress_snapshot=ingress_snapshot)
    with _REPORT_LOCK:
        _REPORT_CACHE = report
    return report


def candidate_report_snapshot() -> dict[str, object]:
    with _REPORT_LOCK:
        return copy.deepcopy(_REPORT_CACHE)


def register_message_runtime_candidate_router(router: APIRouter, *, x: str) -> None:
    @router.get(f"{x}/message-runtime/candidates")
    async def message_runtime_candidates() -> dict[str, object]:
        return candidate_report_snapshot()
