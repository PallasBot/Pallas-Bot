from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set
from typing import Any

_BLOCKER_ORDER = (
    "multiple_route_modules",
    "route_index_fallback",
    "direct_error",
    "already_direct",
    "missing_plugin_stats",
    "insufficient_route_identity",
    "private_only",
    "complex_request_flow",
    "community_or_local",
    "intentionally_matcher_only",
)


def number(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return max(0.0, float(value))
    return 0.0


def integer(value: object) -> int:
    return int(number(value))


def compatible_count(row: Mapping[str, object], current: str, historical: str) -> int:
    return integer(row.get(current)) + integer(row.get(historical))


def normalized_modules(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(sorted({str(module).strip() for module in value if str(module).strip()}))


def normalized_outcomes(value: object) -> dict[str, dict[str, int | float | None]]:
    if not isinstance(value, Mapping):
        return {}
    outcomes: dict[str, dict[str, int | float | None]] = {}
    for name in ("direct_handled", "direct_fallback", "direct_error", "matcher_only"):
        raw = value.get(name)
        if not isinstance(raw, Mapping):
            continue
        outcomes[name] = {
            "messages": integer(raw.get("messages")),
            "matchers_considered": integer(raw.get("matchers_considered")),
            "matchers_selected": integer(raw.get("matchers_selected")),
            "matchers_run": integer(raw.get("matchers_run")),
            "ingress_duration_ms_p95": number(raw.get("ingress_duration_ms_p95")) or None,
        }
    return outcomes


def plugin_stats_by_module(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for row in rows:
        module = str(row.get("module") or row.get("name") or "").strip()
        if not module:
            continue
        current = result.setdefault(
            module,
            {"runs": 0, "runs_today": 0, "errors": 0, "errors_today": 0, "duration_ms_today": 0.0},
        )
        current["runs"] = int(current["runs"]) + integer(row.get("runs"))
        current["runs_today"] = int(current["runs_today"]) + integer(row.get("runs_today"))
        current["errors"] = int(current["errors"]) + integer(row.get("errors"))
        current["errors_today"] = int(current["errors_today"]) + integer(row.get("errors_today"))
        current["duration_ms_today"] = float(current["duration_ms_today"]) + number(row.get("duration_ms_today"))
    return result


def rank_message_runtime_candidates(
    *,
    plugin_stats: Sequence[Mapping[str, object]],
    route_candidates: Sequence[Mapping[str, object]],
    passive_modules: Set[str] = frozenset(),
    private_only_modules: Set[str] = frozenset(),
    complex_request_modules: Set[str] = frozenset(),
    risk_labels_by_module: Mapping[str, Sequence[str]] | None = None,
    built_in_modules: Set[str] = frozenset(),
    official_extension_modules: Set[str] = frozenset(),
    direct_modules: Set[str] = frozenset(),
    matcher_only_modules: Set[str] = frozenset(),
    day_key: str,
    generated_at: int,
    route_window: Mapping[str, object],
) -> dict[str, object]:
    stats = plugin_stats_by_module(plugin_stats)
    risks = risk_labels_by_module or {}
    candidates: list[dict[str, Any]] = []
    data_quality: set[str] = set()

    if not route_candidates:
        data_quality.add("missing_route_candidates")
    if not plugin_stats:
        data_quality.add("missing_plugin_stats")

    for raw in route_candidates:
        if not isinstance(raw, Mapping):
            data_quality.add("malformed_route_candidate")
            continue
        modules = normalized_modules(raw.get("route_modules"))
        module = modules[0] if len(modules) == 1 else ",".join(modules)
        messages = integer(raw.get("messages"))
        selected = integer(raw.get("matchers_selected"))
        module_stats = stats.get(module) if len(modules) == 1 else None
        blockers: set[str] = set()
        if len(modules) > 1:
            blockers.add("multiple_route_modules")
        if integer(raw.get("route_index_fallbacks")) > 0:
            blockers.add("route_index_fallback")
        direct_handled = compatible_count(raw, "direct_handled", "native_handled")
        direct_fallback = compatible_count(raw, "direct_fallback", "native_fallback")
        direct_error = compatible_count(raw, "direct_error", "native_error")
        matcher_handled = compatible_count(raw, "matcher_handled", "legacy_handled")
        if direct_error > 0:
            blockers.add("direct_error")
        if messages > 0 and direct_handled >= messages:
            blockers.add("already_direct")
        if module_stats is None:
            blockers.add("missing_plugin_stats")
            data_quality.add("missing_plugin_stats")
        if len(modules) != 1 or messages <= 0:
            blockers.add("insufficient_route_identity")
        if module in private_only_modules:
            blockers.add("private_only")
        if module in complex_request_modules:
            blockers.add("complex_request_flow")
        if module in built_in_modules:
            ownership = "built_in"
        elif module in official_extension_modules:
            ownership = "official_extension"
        else:
            ownership = "community_or_local"
            blockers.add("community_or_local")
        if module in matcher_only_modules:
            blockers.add("intentionally_matcher_only")
        runtime_path = "direct" if module in direct_modules else "matcher"

        average_selected = round(selected / messages, 4) if messages > 0 else None
        runs_today = int(module_stats["runs_today"]) if module_stats else 0
        estimate = (
            round(runs_today * average_selected, 2)
            if len(modules) == 1 and module_stats is not None and average_selected is not None
            else None
        )
        labels = set(risks.get(module, ()))
        if module in passive_modules:
            labels.add("passive_frequency_inflated")
        ordered_blockers = [label for label in _BLOCKER_ORDER if label in blockers]
        candidates.append({
            "module": module,
            "route_modules": list(modules),
            "runs_today": runs_today,
            "runs_total": int(module_stats["runs"]) if module_stats else 0,
            "errors_today": int(module_stats["errors_today"]) if module_stats else 0,
            "errors_total": int(module_stats["errors"]) if module_stats else 0,
            "current_day_duration_ms": round(float(module_stats["duration_ms_today"]), 2) if module_stats else 0.0,
            "route_messages": messages,
            "route_index_hits": integer(raw.get("route_index_hits")),
            "route_index_fallbacks": integer(raw.get("route_index_fallbacks")),
            "matchers_considered": integer(raw.get("matchers_considered")),
            "matchers_selected": selected,
            "matchers_run": integer(raw.get("matchers_run")),
            "direct_handled": direct_handled,
            "direct_fallback": direct_fallback,
            "direct_error": direct_error,
            "matcher_handled": matcher_handled,
            "outcomes": normalized_outcomes(raw.get("outcomes")),
            "average_matchers_selected_per_route_message": average_selected,
            "ingress_duration_ms_p95": number(raw.get("ingress_duration_ms_p95")) or None,
            "estimated_matchers_avoided_today": estimate,
            "confidence": "high" if messages >= 20 else "medium" if messages >= 5 else "low",
            "blockers": ordered_blockers,
            "risk_labels": sorted(labels),
            "ownership": ownership,
            "runtime_path": runtime_path,
            "eligible": not ordered_blockers,
        })

    candidates.sort(
        key=lambda row: (
            not bool(row["eligible"]),
            -float(row["estimated_matchers_avoided_today"] or 0),
            -float(row["current_day_duration_ms"]),
            str(row["module"]),
        )
    )
    return {
        "day_key": day_key,
        "generated_at": int(generated_at),
        "route_window": dict(route_window),
        "candidates": candidates,
        "data_quality": sorted(data_quality),
    }
