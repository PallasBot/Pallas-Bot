"""LLM token 累计统计（Bot 直连 provider 返回 usage 时解析）。"""

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
_prompt_tokens = 0
_completion_tokens = 0
_cache_read_tokens = 0
_cache_write_tokens = 0
_cost_total = 0.0
_cost_currency = ""
_by_task: dict[str, dict[str, Any]] = {}
_by_provider: dict[str, dict[str, Any]] = {}
_by_model: dict[str, dict[str, Any]] = {}
_by_hour: dict[str, dict[str, Any]] = {}

_EMPTY_ROW: dict[str, Any] = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "cost_total": 0.0,
}


def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def stats_file_path():
    return plugin_data_dir("pb_webui", create=True) / "llm_token_stats.json"


def _as_cost(raw: object) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if value != value or value < 0:
        return 0.0
    return value


def _copy_breakdown_from_persisted(dst: dict[str, dict[str, Any]], src: Any) -> None:
    if not isinstance(src, dict):
        return
    for key, metrics in src.items():
        if not isinstance(metrics, dict):
            continue
        k = str(key).strip()
        if not k:
            continue
        dst[k] = {
            "prompt_tokens": int(metrics.get("prompt_tokens") or 0),
            "completion_tokens": int(metrics.get("completion_tokens") or 0),
            "cache_read_tokens": int(metrics.get("cache_read_tokens") or 0),
            "cache_write_tokens": int(metrics.get("cache_write_tokens") or 0),
            "cost_total": _as_cost(metrics.get("cost_total")),
        }


def _hydrate_from_disk_locked() -> None:
    """进程内只 hydrate 一次：把当日落盘计数载入内存，避免与内存再次相加。"""
    global _hydrated, _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens, _cost_total, _cost_currency  # noqa: PLW0603, E501
    if _hydrated:
        return
    _hydrated = True
    today = str(_day_key or today_key()).strip()[:10]

    def apply_raw(raw: dict[str, Any]) -> None:
        global _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens, _cost_total, _cost_currency  # noqa: PLW0603, E501
        if (
            _prompt_tokens
            or _completion_tokens
            or _cache_read_tokens
            or _cache_write_tokens
            or _cost_total
            or _by_task
            or _by_provider
            or _by_model
            or _by_hour
        ):
            return
        _prompt_tokens = int(raw.get("prompt_tokens") or 0)
        _completion_tokens = int(raw.get("completion_tokens") or 0)
        _cache_read_tokens = int(raw.get("cache_read_tokens") or 0)
        _cache_write_tokens = int(raw.get("cache_write_tokens") or 0)
        _cost_total = _as_cost(raw.get("cost_total"))
        _cost_currency = str(raw.get("cost_currency") or "").strip().upper()
        _copy_breakdown_from_persisted(_by_task, raw.get("by_task"))
        _copy_breakdown_from_persisted(_by_provider, raw.get("by_provider"))
        _copy_breakdown_from_persisted(_by_model, raw.get("by_model"))
        _copy_breakdown_from_persisted(_by_hour, raw.get("by_hour"))

    try:
        from pallas.product.llm.shard_metric_hydrate import (
            allow_shared_stats_file_hydrate,
            load_worker_day_metric,
        )

        worker_raw = load_worker_day_metric(metric_key="llm_token", day_key=today)
        if isinstance(worker_raw, dict):
            apply_raw(worker_raw)
            return
        if not allow_shared_stats_file_hydrate():
            return
    except Exception:
        pass

    raw = load_stats_file()
    if not isinstance(raw, dict) or not raw.get("day_key"):
        return
    file_day = str(raw.get("day_key") or "").strip()[:10]
    if file_day and file_day != today:
        try:
            from pallas.product.llm.llm_daily_stats_store import write_day_side

            write_day_side(
                file_day,
                "ai",
                {"tokens": {**raw, "day_key": file_day, "source": "bot"}, "day_key": file_day, "source": "bot"},
            )
        except Exception:
            pass
        return
    apply_raw(raw)


def rollover_if_needed() -> None:
    global _day_key, _hydrated, _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens, _cost_total, _cost_currency  # noqa: PLW0603, E501
    today = today_key()
    if _day_key == today:
        return
    if _day_key:
        try:
            from pallas.product.llm.llm_daily_stats_store import write_day_side

            old = _snapshot_locked(day_override=_day_key)
            # 写入当日 AI 侧 tokens 槽（控制台以 ai.tokens 展示）
            write_day_side(_day_key, "ai", {"tokens": old, "day_key": _day_key, "source": "bot"})
        except Exception:
            pass
        _prompt_tokens = 0
        _completion_tokens = 0
        _cache_read_tokens = 0
        _cache_write_tokens = 0
        _cost_total = 0.0
        _cost_currency = ""
        _by_task.clear()
        _by_provider.clear()
        _by_model.clear()
        _by_hour.clear()
        _day_key = today
        _hydrated = True
        return
    # 进程首次进入当日：先定 day_key，由 hydrate 按需载入落盘
    _day_key = today
    _hydrated = False


def _bump_row(
    row: dict[str, Any],
    *,
    prompt: int,
    completion: int,
    cache_read: int,
    cache_write: int,
    cost: float = 0.0,
) -> None:
    row["prompt_tokens"] = int(row.get("prompt_tokens") or 0) + prompt
    row["completion_tokens"] = int(row.get("completion_tokens") or 0) + completion
    row["cache_read_tokens"] = int(row.get("cache_read_tokens") or 0) + cache_read
    row["cache_write_tokens"] = int(row.get("cache_write_tokens") or 0) + cache_write
    if cost:
        row["cost_total"] = round(_as_cost(row.get("cost_total")) + cost, 6)


def record_llm_token_usage(
    *,
    task: str | None,
    provider: str | None = None,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    prompt = max(0, int(prompt_tokens))
    completion = max(0, int(completion_tokens))
    cache_read = max(0, int(cache_read_tokens))
    cache_write = max(0, int(cache_write_tokens))
    if prompt == 0 and completion == 0 and cache_read == 0 and cache_write == 0:
        return
    task_key = str(task or "llm_chat").strip().lower() or "llm_chat"
    cost = 0.0
    currency = ""
    try:
        from pallas.product.llm.token_cost import cost_for_usage

        cost, currency = cost_for_usage(
            provider_id=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
    except Exception:
        cost = 0.0
        currency = ""
    day_for_ledger = today_key()
    try:
        with _lock:
            rollover_if_needed()
            _hydrate_from_disk_locked()
            global _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens, _cost_total, _cost_currency  # noqa: PLW0603, E501
            _prompt_tokens += prompt
            _completion_tokens += completion
            _cache_read_tokens += cache_read
            _cache_write_tokens += cache_write
            if cost > 0:
                _cost_total = round(_cost_total + cost, 6)
            if currency and not _cost_currency:
                _cost_currency = currency
            row = _by_task.setdefault(task_key, dict(_EMPTY_ROW))
            _bump_row(
                row,
                prompt=prompt,
                completion=completion,
                cache_read=cache_read,
                cache_write=cache_write,
                cost=cost,
            )
            provider_key = str(provider or "").strip().lower()
            if provider_key:
                prow = _by_provider.setdefault(provider_key, dict(_EMPTY_ROW))
                _bump_row(
                    prow,
                    prompt=prompt,
                    completion=completion,
                    cache_read=cache_read,
                    cache_write=cache_write,
                    cost=cost,
                )
            model_key = str(model or "").strip()
            if model_key:
                mrow = _by_model.setdefault(model_key, dict(_EMPTY_ROW))
                _bump_row(
                    mrow,
                    prompt=prompt,
                    completion=completion,
                    cache_read=cache_read,
                    cache_write=cache_write,
                    cost=cost,
                )
            hour_key = time.strftime("%H", time.localtime())
            hrow = _by_hour.setdefault(hour_key, dict(_EMPTY_ROW))
            _bump_row(
                hrow,
                prompt=prompt,
                completion=completion,
                cache_read=cache_read,
                cache_write=cache_write,
                cost=cost,
            )
            day_for_ledger = _day_key or today_key()
        from pallas.product.llm.usage_ledger import append_usage_record

        append_usage_record(
            task=task_key,
            provider=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost=cost,
            currency=currency,
            day_key=day_for_ledger,
        )
    except Exception:
        pass


def _row_with_total(values: dict[str, Any]) -> dict[str, Any]:
    prompt = int(values.get("prompt_tokens") or 0)
    completion = int(values.get("completion_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_tokens": int(values.get("cache_read_tokens") or 0),
        "cache_write_tokens": int(values.get("cache_write_tokens") or 0),
        "total_tokens": prompt + completion,
        "cost_total": _as_cost(values.get("cost_total")),
    }


def _snapshot_locked(*, day_override: str | None = None) -> dict[str, Any]:
    return {
        "source": "bot",
        "day_key": day_override or _day_key or today_key(),
        "updated_at": time.time(),
        "prompt_tokens": _prompt_tokens,
        "completion_tokens": _completion_tokens,
        "cache_read_tokens": _cache_read_tokens,
        "cache_write_tokens": _cache_write_tokens,
        "total_tokens": _prompt_tokens + _completion_tokens,
        "cost_total": _cost_total,
        "cost_currency": _cost_currency,
        "by_task": {task: _row_with_total(values) for task, values in _by_task.items()},
        "by_provider": {key: _row_with_total(values) for key, values in _by_provider.items()},
        "by_model": {key: _row_with_total(values) for key, values in _by_model.items()},
        "by_hour": {hour: _row_with_total(values) for hour, values in sorted(_by_hour.items())},
    }


def load_stats_file() -> dict[str, Any]:
    path = stats_file_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _merge_breakdown(dst: dict[str, dict[str, Any]], src: Any) -> None:
    if not isinstance(src, dict):
        return
    for key, metrics in src.items():
        if not isinstance(metrics, dict):
            continue
        k = str(key).strip()
        if not k:
            continue
        row = dst.setdefault(k, dict(_EMPTY_ROW))
        _bump_row(
            row,
            prompt=int(metrics.get("prompt_tokens") or 0),
            completion=int(metrics.get("completion_tokens") or 0),
            cache_read=int(metrics.get("cache_read_tokens") or 0),
            cache_write=int(metrics.get("cache_write_tokens") or 0),
            cost=_as_cost(metrics.get("cost_total")),
        )


def merge_llm_token_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_hour: dict[str, dict[str, Any]] = {}
    prompt_tokens = 0
    completion_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    cost_total = 0.0
    cost_currency = ""
    day_key = ""
    updated_at = 0.0
    source = "bot"
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        source = str(row.get("source") or source)
        try:
            updated_at = max(updated_at, float(row.get("updated_at") or 0))
        except (TypeError, ValueError):
            pass
        prompt_tokens += int(row.get("prompt_tokens") or 0)
        completion_tokens += int(row.get("completion_tokens") or 0)
        cache_read_tokens += int(row.get("cache_read_tokens") or 0)
        cache_write_tokens += int(row.get("cache_write_tokens") or 0)
        cost_total += _as_cost(row.get("cost_total"))
        if not cost_currency:
            cost_currency = str(row.get("cost_currency") or "").strip().upper()
        _merge_breakdown(by_task, row.get("by_task"))
        _merge_breakdown(by_provider, row.get("by_provider"))
        _merge_breakdown(by_model, row.get("by_model"))
        _merge_breakdown(by_hour, row.get("by_hour"))
    return {
        "source": source or "bot",
        "day_key": day_key or today_key(),
        "updated_at": updated_at or time.time(),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_total": cost_total,
        "cost_currency": cost_currency,
        "by_task": {k: _row_with_total(v) for k, v in by_task.items()},
        "by_provider": {k: _row_with_total(v) for k, v in by_provider.items()},
        "by_model": {k: _row_with_total(v) for k, v in by_model.items()},
        "by_hour": {k: _row_with_total(v) for k, v in sorted(by_hour.items())},
    }


def llm_token_metrics_snapshot(*, include_persisted: bool = True) -> dict[str, Any]:
    with _lock:
        rollover_if_needed()
        if include_persisted:
            _hydrate_from_disk_locked()
        return _snapshot_locked()


def cluster_llm_token_metrics_snapshot(*, max_stale_sec: float = 300.0) -> dict[str, Any]:
    """分片 hub：合并本进程与各 worker stats 中的 llm_token 快照。"""
    rows = [llm_token_metrics_snapshot(include_persisted=True)]
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            from pallas.core.platform.shard.console_stats import iter_worker_shard_ids, read_worker_stats_file

            for shard_id in iter_worker_shard_ids(max_stale_sec=max_stale_sec):
                blob = read_worker_stats_file(shard_id)
                llm = blob.get("llm_token")
                if not isinstance(llm, dict):
                    continue
                if (
                    int(llm.get("total_tokens") or 0) <= 0
                    and not llm.get("by_task")
                    and not llm.get("by_provider")
                    and _as_cost(llm.get("cost_total")) <= 0
                ):
                    continue
                rows.append(llm)
    except Exception:
        pass
    if len(rows) <= 1:
        out = rows[0]
        if isinstance(out, dict):
            return {**out, "source": "bot_cluster" if len(rows) > 1 else out.get("source") or "bot"}
        return out
    merged = merge_llm_token_snapshots(rows)
    merged["source"] = "bot_cluster"
    return merged


def flush_stats_sync() -> None:
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_worker():
            return
        # 只落盘本进程内存（经 hydrate），禁止再与磁盘快照相加，否则刷新统计会翻倍漂移
        snapshot = llm_token_metrics_snapshot(include_persisted=True)
    except Exception:
        snapshot = llm_token_metrics_snapshot(include_persisted=True)
    if not snapshot.get("by_task") and int(snapshot.get("total_tokens") or 0) == 0:
        if (
            int(snapshot.get("cache_read_tokens") or 0) == 0
            and int(snapshot.get("cache_write_tokens") or 0) == 0
            and _as_cost(snapshot.get("cost_total")) <= 0
        ):
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
        from pallas.product.llm.usage_ledger import trim_old_ledger_files

        trim_old_ledger_files()
    except Exception:
        pass
    try:
        from pallas.product.llm.llm_daily_stats_store import write_day_side

        write_day_side(
            str(snapshot.get("day_key") or today_key()),
            "ai",
            {"tokens": snapshot, "day_key": snapshot.get("day_key"), "source": "bot"},
        )
    except Exception:
        pass


def clear_llm_token_metrics_for_tests() -> None:
    global _day_key, _hydrated, _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens, _cost_total, _cost_currency  # noqa: PLW0603, E501
    with _lock:
        _day_key = today_key()
        _hydrated = True
        _prompt_tokens = 0
        _completion_tokens = 0
        _cache_read_tokens = 0
        _cache_write_tokens = 0
        _cost_total = 0.0
        _cost_currency = ""
        _by_task.clear()
        _by_provider.clear()
        _by_model.clear()
        _by_hour.clear()
