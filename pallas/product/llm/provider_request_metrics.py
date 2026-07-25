"""Bot 内核：按提供方 / 模型累计请求成功失败与耗时（控制台「提供方请求」）。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

_STORE_VER = 1

_lock = threading.Lock()
_day_key = ""
_hydrated = False
_by_provider: dict[str, dict[str, Any]] = {}
_by_model: dict[str, dict[str, Any]] = {}
_failure_counts: dict[str, int] = {}

_EMPTY_ROW: dict[str, Any] = {
    "requests": 0,
    "succeeded": 0,
    "failed": 0,
    "total_latency_ms": 0,
    "recent_failure_class": "",
}


def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def stats_file_path():
    return plugin_data_dir("pb_webui", create=True) / "llm_provider_request_stats.json"


def _empty_row() -> dict[str, Any]:
    return dict(_EMPTY_ROW)


def _normalize_key(raw: str | None, *, fallback: str) -> str:
    key = str(raw or "").strip()
    return key or fallback


def _bump_row(row: dict[str, Any], *, ok: bool, latency_ms: int, failure_class: str) -> None:
    row["requests"] = int(row.get("requests") or 0) + 1
    if ok:
        row["succeeded"] = int(row.get("succeeded") or 0) + 1
    else:
        row["failed"] = int(row.get("failed") or 0) + 1
        cls = str(failure_class or "").strip()
        if cls:
            row["recent_failure_class"] = cls
    row["total_latency_ms"] = int(row.get("total_latency_ms") or 0) + max(0, int(latency_ms))


def _row_with_avg(row: dict[str, Any]) -> dict[str, Any]:
    requests = int(row.get("requests") or 0)
    total_latency = int(row.get("total_latency_ms") or 0)
    avg = (total_latency / requests) if requests > 0 else None
    recent = str(row.get("recent_failure_class") or "").strip()
    return {
        "requests": requests,
        "succeeded": int(row.get("succeeded") or 0),
        "failed": int(row.get("failed") or 0),
        "total_latency_ms": total_latency,
        "avg_latency_ms": avg,
        "recent_failure_class": recent or None,
    }


def rollover_if_needed() -> None:
    global _day_key, _hydrated  # noqa: PLW0603
    today = today_key()
    if _day_key == today:
        return
    if _day_key:
        try:
            from pallas.product.llm.llm_daily_stats_store import write_day_side

            old = _snapshot_locked(day_override=_day_key)
            write_day_side(
                _day_key,
                "ai",
                {
                    "day_key": _day_key,
                    "source": "bot",
                    "provider_stats": old.get("provider_stats") or {},
                    "model_stats": old.get("model_stats") or {},
                    "failure_counts": old.get("failure_counts") or {},
                },
            )
        except Exception:
            pass
        _by_provider.clear()
        _by_model.clear()
        _failure_counts.clear()
        _day_key = today
        _hydrated = True
        return
    _day_key = today
    _hydrated = False


def _copy_dimension_from_persisted(dst: dict[str, dict[str, Any]], src: Any) -> None:
    if not isinstance(src, dict):
        return
    for key, row in src.items():
        if not isinstance(row, dict):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        dst[name] = {
            "requests": int(row.get("requests") or 0),
            "succeeded": int(row.get("succeeded") or row.get("ok") or 0),
            "failed": int(row.get("failed") or row.get("fail") or 0),
            "total_latency_ms": int(row.get("total_latency_ms") or 0),
            "recent_failure_class": str(row.get("recent_failure_class") or "").strip(),
        }


def _hydrate_from_disk_locked() -> None:
    global _hydrated  # noqa: PLW0603
    if _hydrated:
        return
    _hydrated = True
    raw = load_stats_file()
    if not isinstance(raw, dict) or not raw.get("day_key"):
        return
    if str(raw.get("day_key") or "") != str(_day_key or today_key()):
        return
    if _by_provider or _by_model or _failure_counts:
        return
    _copy_dimension_from_persisted(_by_provider, raw.get("provider_stats"))
    _copy_dimension_from_persisted(_by_model, raw.get("model_stats"))
    fails = raw.get("failure_counts")
    if isinstance(fails, dict):
        for key, count in fails.items():
            name = str(key or "").strip()
            if name:
                _failure_counts[name] = int(count or 0)


def _snapshot_locked(*, day_override: str | None = None) -> dict[str, Any]:
    return {
        "source": "bot",
        "day_key": day_override or _day_key or today_key(),
        "updated_at": time.time(),
        "provider_stats": {key: _row_with_avg(values) for key, values in _by_provider.items()},
        "model_stats": {key: _row_with_avg(values) for key, values in _by_model.items()},
        "failure_counts": {key: int(count) for key, count in _failure_counts.items() if int(count) > 0},
    }


def record_provider_request(
    *,
    provider: str | None,
    model: str | None = None,
    ok: bool,
    latency_ms: int = 0,
    failure_class: str | None = None,
) -> None:
    provider_key = _normalize_key(provider, fallback="unknown")
    model_key = _normalize_key(model, fallback="")
    latency = max(0, int(latency_ms))
    fail_cls = str(failure_class or "").strip()
    with _lock:
        rollover_if_needed()
        _hydrate_from_disk_locked()
        prow = _by_provider.setdefault(provider_key, _empty_row())
        _bump_row(prow, ok=ok, latency_ms=latency, failure_class=fail_cls)
        if model_key:
            mrow = _by_model.setdefault(model_key, _empty_row())
            _bump_row(mrow, ok=ok, latency_ms=latency, failure_class=fail_cls)
        if not ok and fail_cls:
            _failure_counts[fail_cls] = int(_failure_counts.get(fail_cls) or 0) + 1


def load_stats_file() -> dict[str, Any] | None:
    path = stats_file_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _merge_dimension(dst: dict[str, dict[str, Any]], src: Any) -> None:
    if not isinstance(src, dict):
        return
    for key, row in src.items():
        if not isinstance(row, dict):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        cur = dst.setdefault(name, _empty_row())
        cur["requests"] = int(cur.get("requests") or 0) + int(row.get("requests") or 0)
        cur["succeeded"] = int(cur.get("succeeded") or 0) + int(row.get("succeeded") or row.get("ok") or 0)
        cur["failed"] = int(cur.get("failed") or 0) + int(row.get("failed") or row.get("fail") or 0)
        cur["total_latency_ms"] = int(cur.get("total_latency_ms") or 0) + int(row.get("total_latency_ms") or 0)
        recent = str(row.get("recent_failure_class") or "").strip()
        if recent:
            cur["recent_failure_class"] = recent


def merge_provider_request_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_provider: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    failure_counts: dict[str, int] = {}
    day_key = ""
    updated_at = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key or "")
        updated_at = max(updated_at, float(row.get("updated_at") or 0))
        _merge_dimension(by_provider, row.get("provider_stats"))
        _merge_dimension(by_model, row.get("model_stats"))
        fails = row.get("failure_counts")
        if isinstance(fails, dict):
            for key, count in fails.items():
                name = str(key or "").strip()
                if not name:
                    continue
                failure_counts[name] = int(failure_counts.get(name) or 0) + int(count or 0)
    return {
        "source": "bot",
        "day_key": day_key or today_key(),
        "updated_at": updated_at or time.time(),
        "provider_stats": {key: _row_with_avg(values) for key, values in by_provider.items()},
        "model_stats": {key: _row_with_avg(values) for key, values in by_model.items()},
        "failure_counts": {key: int(count) for key, count in failure_counts.items() if int(count) > 0},
    }


def llm_provider_request_metrics_snapshot(*, include_persisted: bool = True) -> dict[str, Any]:
    with _lock:
        rollover_if_needed()
        if include_persisted:
            _hydrate_from_disk_locked()
        return _snapshot_locked()


def cluster_llm_provider_request_metrics_snapshot(*, max_stale_sec: float = 300.0) -> dict[str, Any]:
    """分片 hub：合并本进程与各 worker stats 中的 llm_provider_request 快照。"""
    rows = [llm_provider_request_metrics_snapshot(include_persisted=True)]
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            from pallas.core.platform.shard.console_stats import iter_worker_shard_ids, read_worker_stats_file

            for shard_id in iter_worker_shard_ids(max_stale_sec=max_stale_sec):
                blob = read_worker_stats_file(shard_id)
                llm = blob.get("llm_provider_request")
                if not isinstance(llm, dict):
                    continue
                if not llm.get("provider_stats") and not llm.get("model_stats"):
                    continue
                rows.append(llm)
    except Exception:
        pass
    if len(rows) <= 1:
        out = rows[0]
        if isinstance(out, dict):
            return {**out, "source": "bot_cluster" if len(rows) > 1 else out.get("source") or "bot"}
        return out
    merged = merge_provider_request_snapshots(rows)
    merged["source"] = "bot_cluster"
    return merged


def flush_provider_request_stats_sync() -> None:
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_worker():
            return
        snapshot = llm_provider_request_metrics_snapshot(include_persisted=True)
    except Exception:
        snapshot = llm_provider_request_metrics_snapshot(include_persisted=True)
    if not snapshot.get("provider_stats") and not snapshot.get("model_stats"):
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

        write_day_side(
            str(snapshot.get("day_key") or today_key()),
            "ai",
            {
                "day_key": snapshot.get("day_key"),
                "source": "bot",
                "provider_stats": snapshot.get("provider_stats") or {},
                "model_stats": snapshot.get("model_stats") or {},
                "failure_counts": snapshot.get("failure_counts") or {},
            },
        )
    except Exception:
        pass


def clear_llm_provider_request_metrics_for_tests() -> None:
    global _day_key, _hydrated  # noqa: PLW0603
    with _lock:
        _day_key = today_key()
        _hydrated = True
        _by_provider.clear()
        _by_model.clear()
        _failure_counts.clear()
