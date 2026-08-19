from __future__ import annotations

import json
import math
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .data_dir import pb_webui_data_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

INGRESS_HISTORY_RETENTION_SEC = 7 * 24 * 60 * 60
_COUNTER_KEYS = (
    "group_messages",
    "learn_enqueued",
    "learn_persisted",
    "work_completed",
    "scheduler_backpressure_waits",
    "scheduler_per_key_backpressure_waits",
)
_ROUTE_CANDIDATE_COUNTER_KEYS = (
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
_OUTCOME_KEYS = ("direct_handled", "direct_fallback", "direct_error", "matcher_only")
_OUTCOME_COUNTER_KEYS = ("messages", "matchers_considered", "matchers_selected", "matchers_run")
_RUNTIME_STAGE_NAMES = ("handler", "send", "deferred_wait", "deferred_submit", "commit")
_HISTORY_LOCK = threading.Lock()
_last_prune_at = 0
_ROUTE_HISTORY_CACHE: dict[str, Any] = {
    "retention_sec": INGRESS_HISTORY_RETENTION_SEC,
    "day_key": "",
    "latest": [],
    "today_totals": [],
    "write_ok": True,
    "sharded": False,
    "_last_by_route": {},
    "_totals_by_route": {},
}
_ROUTE_HISTORY_CACHE_PATH = ""


def ingress_metrics_history_path() -> Path:
    return pb_webui_data_dir() / "ingress_metrics_history.jsonl"


@contextmanager
def _interprocess_history_lock(path: Path) -> Iterator[None]:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        yield


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _sanitize_route_candidates(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        modules = item.get("route_modules")
        if not isinstance(modules, list):
            continue
        row: dict[str, Any] = {
            "route_modules": sorted({str(module).strip() for module in modules if str(module).strip()}),
        }
        for key in _ROUTE_CANDIDATE_COUNTER_KEYS:
            historical_key = {
                "direct_handled": "native_handled",
                "direct_fallback": "native_fallback",
                "direct_error": "native_error",
                "matcher_handled": "legacy_handled",
                "direct_visible_actions": "native_visible_actions",
                "direct_effect_actions": "native_effect_actions",
            }.get(key)
            value = int(item.get(key) or 0) + int(item.get(historical_key) or 0) if historical_key else item.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                row[key] = max(0, int(value))
        p95 = item.get("ingress_duration_ms_p95")
        if isinstance(p95, (int, float)) and not isinstance(p95, bool) and math.isfinite(float(p95)):
            row["ingress_duration_ms_p95"] = max(0.0, float(p95))
        full_p95 = item.get("ingress_full_ms_p95")
        if isinstance(full_p95, (int, float)) and not isinstance(full_p95, bool) and math.isfinite(float(full_p95)):
            row["ingress_full_ms_p95"] = max(0.0, float(full_p95))
        if isinstance(item.get("eligible"), bool):
            row["eligible"] = item["eligible"]
        runtime_stages = item.get("runtime_stages")
        if isinstance(runtime_stages, dict):
            sanitized_stages: dict[str, dict[str, int | float]] = {}
            for name in _RUNTIME_STAGE_NAMES:
                raw_stage = runtime_stages.get(name)
                if not isinstance(raw_stage, dict):
                    continue
                samples = raw_stage.get("samples")
                p95 = raw_stage.get("p95_ms")
                if (
                    isinstance(samples, (int, float))
                    and not isinstance(samples, bool)
                    and math.isfinite(float(samples))
                    and isinstance(p95, (int, float))
                    and not isinstance(p95, bool)
                    and math.isfinite(float(p95))
                ):
                    sanitized_stages[name] = {"samples": max(0, int(samples)), "p95_ms": max(0.0, float(p95))}
            if sanitized_stages:
                row["runtime_stages"] = sanitized_stages
        outcomes = item.get("outcomes")
        if isinstance(outcomes, dict):
            sanitized_outcomes: dict[str, dict[str, int | float]] = {}
            for outcome in _OUTCOME_KEYS:
                raw_outcome = outcomes.get(outcome)
                if not isinstance(raw_outcome, dict):
                    continue
                sanitized: dict[str, int | float] = {}
                for key in _OUTCOME_COUNTER_KEYS:
                    value = raw_outcome.get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                        sanitized[key] = max(0, int(value))
                p95 = raw_outcome.get("ingress_duration_ms_p95")
                if isinstance(p95, (int, float)) and not isinstance(p95, bool) and math.isfinite(float(p95)):
                    sanitized["ingress_duration_ms_p95"] = max(0.0, float(p95))
                if sanitized:
                    sanitized_outcomes[outcome] = sanitized
            if sanitized_outcomes:
                row["outcomes"] = sanitized_outcomes
        candidates.append(row)
    candidates.sort(key=lambda row: tuple(row["route_modules"]))
    return candidates


def _sample(snapshot: dict[str, Any], *, ts: int) -> dict[str, Any]:
    scheduler = snapshot.get("conversation_scheduler")
    scheduler = scheduler if isinstance(scheduler, dict) else {}
    work = snapshot.get("work_aux") if isinstance(snapshot.get("work_aux"), dict) else {}
    hotpath = snapshot.get("hotpath") if isinstance(snapshot.get("hotpath"), dict) else {}
    send_queue = snapshot.get("send_queue") if isinstance(snapshot.get("send_queue"), dict) else {}
    pool = snapshot.get("pool_budget") if isinstance(snapshot.get("pool_budget"), dict) else {}
    row = {
        "ts": int(ts),
        "ingress_p95_ms": _number(snapshot.get("ingress_duration_ms_p95")),
        "ingress_full_p95_ms": _number(snapshot.get("ingress_full_ms_p95")),
        "scheduler_wait_p95_ms": _number(scheduler.get("wait_ms_p95")),
        "scheduler_run_p95_ms": _number(scheduler.get("run_ms_p95")),
        "scheduler_pending": int(scheduler.get("pending") or 0),
        "scheduler_active": int(scheduler.get("active") or 0),
        "scheduler_capacity": int(scheduler.get("concurrency") or 0),
        "scheduler_backpressure_waits": int(scheduler.get("backpressure_waits") or 0),
        "scheduler_per_key_backpressure_waits": int(scheduler.get("per_key_backpressure_waits") or 0),
        "passive_repeater_pending": int(scheduler.get("passive_repeater_pending") or 0),
        "passive_repeater_active": int(scheduler.get("passive_repeater_active") or 0),
        "passive_llm_pending": int(scheduler.get("passive_llm_pending") or 0),
        "passive_llm_active": int(scheduler.get("passive_llm_active") or 0),
        "send_queue_depth": int(send_queue.get("depth_live", send_queue.get("depth", 0)) or 0),
        "send_queue_capacity": int(send_queue.get("max_depth") or 0),
        "pg_pool_utilization": _number(pool.get("utilization")),
        "work_pending": int(work.get("pending") or 0),
        "work_leased": int(work.get("leased") or 0),
        "group_messages": int(snapshot.get("group_messages") or 0),
        "learn_enqueued": int(hotpath.get("learn_enqueued") or 0),
        "learn_persisted": int(hotpath.get("learn_persisted") or 0),
        "work_completed": int(work.get("completed_since_start") or 0),
    }
    day_key = snapshot.get("day_key")
    if isinstance(day_key, str) and day_key:
        row["day_key"] = day_key
    row["sharded"] = bool(snapshot.get("sharded"))
    return row


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("ts"), int):
            rows.append(row)
    return rows


def _candidate_changes(rows: list[dict[str, Any]], *, cutoff: int, now: int) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: int(item["ts"])):
        ts = int(row["ts"])
        candidates = row.get("route_candidates")
        if ts <= cutoff or ts > now or not isinstance(candidates, list):
            continue
        changes.append({
            "ts": ts,
            "day_key": str(row.get("day_key") or ""),
            "sharded": bool(row.get("sharded")),
            "route_candidates": _sanitize_route_candidates(candidates),
        })
    return changes


def _apply_candidate_delta(
    *,
    candidates: list[dict[str, Any]],
    previous: dict[tuple[str, ...], dict[str, Any]],
    totals: dict[tuple[str, ...], dict[str, Any]],
) -> dict[tuple[str, ...], dict[str, Any]]:
    current: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in candidates:
        route = tuple(row["route_modules"])
        current[route] = row
        total = totals.setdefault(
            route,
            {"route_modules": list(route), **dict.fromkeys(_ROUTE_CANDIDATE_COUNTER_KEYS, 0)},
        )
        prior = previous.get(route)
        for key in _ROUTE_CANDIDATE_COUNTER_KEYS:
            value = int(row.get(key) or 0)
            prior_value = int(prior.get(key) or 0) if prior is not None else 0
            total[key] += value - prior_value if value >= prior_value else value
        p95 = row.get("ingress_duration_ms_p95")
        if isinstance(p95, (int, float)):
            total["ingress_duration_ms_p95"] = max(
                float(total.get("ingress_duration_ms_p95") or 0.0),
                float(p95),
            )
        full_p95 = row.get("ingress_full_ms_p95")
        if isinstance(full_p95, (int, float)):
            total["ingress_full_ms_p95"] = max(
                float(total.get("ingress_full_ms_p95") or 0.0),
                float(full_p95),
            )
        outcomes = row.get("outcomes")
        prior_outcomes = prior.get("outcomes") if prior is not None else None
        if isinstance(outcomes, dict):
            total_outcomes = total.setdefault("outcomes", {})
            if not isinstance(total_outcomes, dict):
                total_outcomes = {}
                total["outcomes"] = total_outcomes
            for outcome, raw_outcome in outcomes.items():
                if not isinstance(raw_outcome, dict):
                    continue
                aggregate = total_outcomes.setdefault(outcome, {})
                if not isinstance(aggregate, dict):
                    aggregate = {}
                    total_outcomes[outcome] = aggregate
                prior_outcome = prior_outcomes.get(outcome) if isinstance(prior_outcomes, dict) else None
                for key in _OUTCOME_COUNTER_KEYS:
                    value = int(raw_outcome.get(key) or 0)
                    prior_value = int(prior_outcome.get(key) or 0) if isinstance(prior_outcome, dict) else 0
                    delta = value - prior_value if value >= prior_value else value
                    aggregate[key] = int(aggregate.get(key) or 0) + delta
                p95 = raw_outcome.get("ingress_duration_ms_p95")
                if isinstance(p95, (int, float)):
                    aggregate["ingress_duration_ms_p95"] = max(
                        float(aggregate.get("ingress_duration_ms_p95") or 0.0),
                        float(p95),
                    )
        runtime_stages = row.get("runtime_stages")
        prior_stages = prior.get("runtime_stages") if prior is not None else None
        if isinstance(runtime_stages, dict):
            total_stages = total.setdefault("runtime_stages", {})
            if not isinstance(total_stages, dict):
                total_stages = {}
                total["runtime_stages"] = total_stages
            for name, raw_stage in runtime_stages.items():
                if not isinstance(raw_stage, dict):
                    continue
                aggregate = total_stages.setdefault(name, {})
                if not isinstance(aggregate, dict):
                    aggregate = {}
                    total_stages[name] = aggregate
                prior_stage = prior_stages.get(name) if isinstance(prior_stages, dict) else None
                samples = int(raw_stage.get("samples") or 0)
                prior_samples = int(prior_stage.get("samples") or 0) if isinstance(prior_stage, dict) else 0
                aggregate["samples"] = int(aggregate.get("samples") or 0) + (
                    samples - prior_samples if samples >= prior_samples else samples
                )
                p95 = raw_stage.get("p95_ms")
                if isinstance(p95, (int, float)):
                    aggregate["p95_ms"] = max(float(aggregate.get("p95_ms") or 0.0), float(p95))
    return current


def _public_candidate_totals(totals: dict[tuple[str, ...], dict[str, Any]]) -> list[dict[str, Any]]:
    result = list(totals.values())
    for row in result:
        messages = int(row["messages"])
        row.setdefault("ingress_duration_ms_p95", None)
        row["eligible"] = (
            len(row["route_modules"]) == 1
            and int(row["matcher_handled"]) > 0
            and int(row["route_index_fallbacks"]) == 0
            and int(row["direct_error"]) == 0
            and int(row["direct_handled"]) < messages
        )
    result.sort(key=lambda row: tuple(row["route_modules"]))
    return result


def _history_cache_from_rows(rows: list[dict[str, Any]], *, now: int) -> dict[str, Any]:
    changes = _candidate_changes(rows, cutoff=now - INGRESS_HISTORY_RETENTION_SEC, now=now)
    latest = changes[-1] if changes else {}
    day_key = str(latest.get("day_key") or "")
    sharded = bool(latest.get("sharded"))
    previous: dict[tuple[str, ...], dict[str, Any]] = {}
    totals: dict[tuple[str, ...], dict[str, Any]] = {}
    for change in changes:
        if change.get("day_key") != day_key:
            continue
        if sharded:
            break
        previous = _apply_candidate_delta(
            candidates=change["route_candidates"],
            previous=previous,
            totals=totals,
        )
    return {
        "retention_sec": INGRESS_HISTORY_RETENTION_SEC,
        "day_key": day_key,
        "latest": latest.get("route_candidates", []),
        "today_totals": _public_candidate_totals(totals),
        "latest_at": latest.get("ts"),
        "write_ok": True,
        "sharded": sharded,
        "_last_by_route": previous,
        "_totals_by_route": totals,
    }


def hydrate_route_candidate_history_cache(*, now: int | None = None) -> None:
    global _ROUTE_HISTORY_CACHE, _ROUTE_HISTORY_CACHE_PATH
    now_sec = int(now if now is not None else time.time())
    path = ingress_metrics_history_path()
    with _HISTORY_LOCK:
        _ROUTE_HISTORY_CACHE = _history_cache_from_rows(_read_rows(path), now=now_sec)
        _ROUTE_HISTORY_CACHE_PATH = str(path)


def prune_ingress_metrics_history(*, now: int | None = None) -> bool:
    path = ingress_metrics_history_path()
    cutoff = int(now if now is not None else time.time()) - INGRESS_HISTORY_RETENTION_SEC
    with _HISTORY_LOCK:
        try:
            with _interprocess_history_lock(path):
                rows = [row for row in _read_rows(path) if int(row["ts"]) > cutoff]
                if not rows:
                    path.unlink(missing_ok=True)
                    return True
                path.parent.mkdir(parents=True, exist_ok=True)
                body = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
                path.write_text(body, encoding="utf-8")
                return True
        except OSError:
            return False


def append_ingress_metrics_history(*, snapshot: dict[str, Any], ts: int | None = None) -> bool:
    global _ROUTE_HISTORY_CACHE, _ROUTE_HISTORY_CACHE_PATH, _last_prune_at
    now = int(ts if ts is not None else time.time())
    path = ingress_metrics_history_path()
    row = _sample(snapshot, ts=now)
    candidates = _sanitize_route_candidates(snapshot.get("route_candidates"))
    with _HISTORY_LOCK:
        if _ROUTE_HISTORY_CACHE_PATH != str(path):
            _ROUTE_HISTORY_CACHE = _history_cache_from_rows(_read_rows(path), now=now)
            _ROUTE_HISTORY_CACHE_PATH = str(path)
        day_key = str(snapshot.get("day_key") or "")
        sharded = bool(snapshot.get("sharded"))
        previous_candidates = _ROUTE_HISTORY_CACHE.get("latest")
        previous_day_key = str(_ROUTE_HISTORY_CACHE.get("day_key") or "")
        previous_sharded = bool(_ROUTE_HISTORY_CACHE.get("sharded"))
        candidates_changed = (
            previous_candidates != candidates or previous_day_key != day_key or previous_sharded != sharded
        )
        if candidates_changed:
            row["route_candidates"] = candidates
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _interprocess_history_lock(path):
                with path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row, separators=(",", ":")) + "\n")
        except OSError:
            _ROUTE_HISTORY_CACHE = {**_ROUTE_HISTORY_CACHE, "write_ok": False}
            return False
        previous = _ROUTE_HISTORY_CACHE.get("_last_by_route")
        totals = _ROUTE_HISTORY_CACHE.get("_totals_by_route")
        if (
            previous_day_key != day_key
            or previous_sharded != sharded
            or not isinstance(previous, dict)
            or not isinstance(totals, dict)
        ):
            previous = {}
            totals = {}
        if candidates_changed and not sharded:
            previous = _apply_candidate_delta(candidates=candidates, previous=previous, totals=totals)
        _ROUTE_HISTORY_CACHE = {
            "retention_sec": INGRESS_HISTORY_RETENTION_SEC,
            "day_key": day_key,
            "latest": candidates,
            "today_totals": _public_candidate_totals(totals),
            "latest_at": now,
            "write_ok": True,
            "sharded": sharded,
            "_last_by_route": previous,
            "_totals_by_route": totals,
        }
    if now - _last_prune_at >= 300:
        _last_prune_at = now
        prune_ingress_metrics_history(now=now)
    return True


def read_route_candidate_history(*, now: int | None = None) -> dict[str, Any]:
    now_sec = int(now if now is not None else time.time())
    rows = _read_rows(ingress_metrics_history_path())
    result = _history_cache_from_rows(rows, now=now_sec)
    return {
        **{key: value for key, value in result.items() if not key.startswith("_")},
        "changes": _candidate_changes(
            rows,
            cutoff=now_sec - INGRESS_HISTORY_RETENTION_SEC,
            now=now_sec,
        ),
    }


def route_candidate_history_snapshot() -> dict[str, Any]:
    with _HISTORY_LOCK:
        return {key: value for key, value in _ROUTE_HISTORY_CACHE.items() if not key.startswith("_")}


def _counter_delta(current: dict[str, Any], previous: dict[str, Any] | None, key: str) -> int:
    value = int(current.get(key) or 0)
    if previous is None:
        return 0
    return max(0, value - int(previous.get(key) or 0))


def _scheduler_counter_delta(current: dict[str, Any], previous: dict[str, Any] | None, key: str) -> int:
    value = int(current.get(key) or 0)
    if previous is None:
        return 0
    previous_value = int(previous.get(key) or 0)
    return value - previous_value if value >= previous_value else value


def read_ingress_metrics_history(*, window_sec: int, bucket_sec: int, now: int | None = None) -> dict[str, Any]:
    now_sec = int(now if now is not None else time.time())
    window = max(60, min(INGRESS_HISTORY_RETENTION_SEC, int(window_sec)))
    bucket = max(15, min(3600, int(bucket_sec)))
    start = now_sec - window
    rows = sorted(_read_rows(ingress_metrics_history_path()), key=lambda row: int(row["ts"]))
    previous = next((row for row in reversed(rows) if int(row["ts"]) < start), None)
    points: dict[int, dict[str, Any]] = {}
    for row in rows:
        ts = int(row["ts"])
        if ts < start or ts > now_sec:
            previous = row
            continue
        at = ts - (ts % bucket)
        point = points.setdefault(
            at,
            {
                "at": at,
                "ingress_p95_ms": 0.0,
                "ingress_full_p95_ms": 0.0,
                "scheduler_wait_p95_ms": 0.0,
                "scheduler_run_p95_ms": 0.0,
                "scheduler_pending": 0,
                "scheduler_active": 0,
                "scheduler_capacity": 0,
                "scheduler_backpressure_waits": 0,
                "scheduler_per_key_backpressure_waits": 0,
                "passive_repeater_pending": 0,
                "passive_repeater_active": 0,
                "passive_llm_pending": 0,
                "passive_llm_active": 0,
                "send_queue_depth": 0,
                "send_queue_capacity": 0,
                "pg_pool_utilization": 0.0,
                "work_pending": 0,
                "work_leased": 0,
                **dict.fromkeys(_COUNTER_KEYS, 0),
            },
        )
        for key in (
            "ingress_p95_ms",
            "ingress_full_p95_ms",
            "scheduler_wait_p95_ms",
            "scheduler_run_p95_ms",
            "pg_pool_utilization",
        ):
            point[key] = max(float(point[key]), float(row.get(key) or 0))
        for key in (
            "scheduler_pending",
            "scheduler_active",
            "scheduler_capacity",
            "send_queue_depth",
            "send_queue_capacity",
            "work_pending",
            "work_leased",
            "passive_repeater_pending",
            "passive_repeater_active",
            "passive_llm_pending",
            "passive_llm_active",
        ):
            point[key] = max(int(point[key]), int(row.get(key) or 0))
        for key in _COUNTER_KEYS:
            delta = _scheduler_counter_delta if key.startswith("scheduler_") else _counter_delta
            point[key] += delta(row, previous, key)
        previous = row
    return {"retention_sec": INGRESS_HISTORY_RETENTION_SEC, "bucket_sec": bucket, "points": list(points.values())}
