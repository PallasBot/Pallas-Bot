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
_prompt_tokens = 0
_completion_tokens = 0
_cache_read_tokens = 0
_cache_write_tokens = 0
_by_task: dict[str, dict[str, int]] = {}
_by_provider: dict[str, dict[str, int]] = {}
_by_model: dict[str, dict[str, int]] = {}

_EMPTY_ROW = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
}


def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def stats_file_path():
    return plugin_data_dir("pb_webui", create=True) / "llm_token_stats.json"


def rollover_if_needed() -> None:
    global _day_key, _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens  # noqa: PLW0603
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
    _day_key = today
    _prompt_tokens = 0
    _completion_tokens = 0
    _cache_read_tokens = 0
    _cache_write_tokens = 0
    _by_task.clear()
    _by_provider.clear()
    _by_model.clear()


def _bump_row(row: dict[str, int], *, prompt: int, completion: int, cache_read: int, cache_write: int) -> None:
    row["prompt_tokens"] = int(row.get("prompt_tokens") or 0) + prompt
    row["completion_tokens"] = int(row.get("completion_tokens") or 0) + completion
    row["cache_read_tokens"] = int(row.get("cache_read_tokens") or 0) + cache_read
    row["cache_write_tokens"] = int(row.get("cache_write_tokens") or 0) + cache_write


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
    try:
        with _lock:
            rollover_if_needed()
            global _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens  # noqa: PLW0603
            _prompt_tokens += prompt
            _completion_tokens += completion
            _cache_read_tokens += cache_read
            _cache_write_tokens += cache_write
            row = _by_task.setdefault(task_key, dict(_EMPTY_ROW))
            _bump_row(row, prompt=prompt, completion=completion, cache_read=cache_read, cache_write=cache_write)
            provider_key = str(provider or "").strip().lower()
            if provider_key:
                prow = _by_provider.setdefault(provider_key, dict(_EMPTY_ROW))
                _bump_row(prow, prompt=prompt, completion=completion, cache_read=cache_read, cache_write=cache_write)
            model_key = str(model or "").strip()
            if model_key:
                mrow = _by_model.setdefault(model_key, dict(_EMPTY_ROW))
                _bump_row(mrow, prompt=prompt, completion=completion, cache_read=cache_read, cache_write=cache_write)
    except Exception:
        pass


def _row_with_total(values: dict[str, int]) -> dict[str, int]:
    prompt = int(values.get("prompt_tokens") or 0)
    completion = int(values.get("completion_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_tokens": int(values.get("cache_read_tokens") or 0),
        "cache_write_tokens": int(values.get("cache_write_tokens") or 0),
        "total_tokens": prompt + completion,
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
        "by_task": {task: _row_with_total(values) for task, values in _by_task.items()},
        "by_provider": {key: _row_with_total(values) for key, values in _by_provider.items()},
        "by_model": {key: _row_with_total(values) for key, values in _by_model.items()},
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


def _merge_breakdown(dst: dict[str, dict[str, int]], src: Any) -> None:
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
        )


def merge_llm_token_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, dict[str, int]] = {}
    by_provider: dict[str, dict[str, int]] = {}
    by_model: dict[str, dict[str, int]] = {}
    prompt_tokens = 0
    completion_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
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
        _merge_breakdown(by_task, row.get("by_task"))
        _merge_breakdown(by_provider, row.get("by_provider"))
        _merge_breakdown(by_model, row.get("by_model"))
    return {
        "source": source or "bot",
        "day_key": day_key or today_key(),
        "updated_at": updated_at or time.time(),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "by_task": {k: _row_with_total(v) for k, v in by_task.items()},
        "by_provider": {k: _row_with_total(v) for k, v in by_provider.items()},
        "by_model": {k: _row_with_total(v) for k, v in by_model.items()},
    }


def llm_token_metrics_snapshot(*, include_persisted: bool = True) -> dict[str, Any]:
    with _lock:
        rollover_if_needed()
        local = _snapshot_locked()
    if not include_persisted:
        return local
    persisted_raw = load_stats_file()
    if not isinstance(persisted_raw, dict) or not persisted_raw.get("day_key"):
        return local
    if str(persisted_raw.get("day_key") or "") != str(local.get("day_key") or ""):
        return local
    persisted = {
        "source": str(persisted_raw.get("source") or "bot"),
        "day_key": str(persisted_raw.get("day_key") or ""),
        "updated_at": float(persisted_raw.get("updated_at") or 0),
        "prompt_tokens": int(persisted_raw.get("prompt_tokens") or 0),
        "completion_tokens": int(persisted_raw.get("completion_tokens") or 0),
        "cache_read_tokens": int(persisted_raw.get("cache_read_tokens") or 0),
        "cache_write_tokens": int(persisted_raw.get("cache_write_tokens") or 0),
        "total_tokens": int(persisted_raw.get("total_tokens") or 0),
        "by_task": persisted_raw.get("by_task") if isinstance(persisted_raw.get("by_task"), dict) else {},
        "by_provider": persisted_raw.get("by_provider") if isinstance(persisted_raw.get("by_provider"), dict) else {},
        "by_model": persisted_raw.get("by_model") if isinstance(persisted_raw.get("by_model"), dict) else {},
    }
    local_has = int(local.get("total_tokens") or 0) > 0 or bool(local.get("by_task"))
    if not local_has:
        return merge_llm_token_snapshots([persisted]) if persisted.get("day_key") else local
    return merge_llm_token_snapshots([persisted, local])


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
                if int(llm.get("total_tokens") or 0) <= 0 and not llm.get("by_task") and not llm.get("by_provider"):
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
        snapshot = (
            cluster_llm_token_metrics_snapshot()
            if shard_ctx.sharding_active() and shard_ctx.is_hub()
            else llm_token_metrics_snapshot(include_persisted=True)
        )
    except Exception:
        snapshot = llm_token_metrics_snapshot(include_persisted=True)
    if not snapshot.get("by_task") and int(snapshot.get("total_tokens") or 0) == 0:
        if int(snapshot.get("cache_read_tokens") or 0) == 0 and int(snapshot.get("cache_write_tokens") or 0) == 0:
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
            {"tokens": snapshot, "day_key": snapshot.get("day_key"), "source": "bot"},
        )
    except Exception:
        pass


def clear_llm_token_metrics_for_tests() -> None:
    global _day_key, _prompt_tokens, _completion_tokens, _cache_read_tokens, _cache_write_tokens  # noqa: PLW0603
    with _lock:
        _day_key = ""
        _prompt_tokens = 0
        _completion_tokens = 0
        _cache_read_tokens = 0
        _cache_write_tokens = 0
        _by_task.clear()
        _by_provider.clear()
        _by_model.clear()
