"""知识库 RAG 查询级命中统计（Bot 内核检索后记账）。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

_STORE_VER = 1

_lock = threading.Lock()
_day_key = ""
_hit_count = 0
_miss_count = 0
_by_document: dict[str, int] = {}
_by_source: dict[str, int] = {}


def today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def stats_file_path():
    return plugin_data_dir("pb_webui", create=True) / "llm_rag_stats.json"


def _hit_rate(hit: int, miss: int) -> float:
    total = hit + miss
    if total <= 0:
        return 0.0
    return round(100.0 * hit / total, 1)


def rollover_if_needed() -> None:
    global _day_key, _hit_count, _miss_count  # noqa: PLW0603
    today = today_key()
    if _day_key == today:
        return
    if _day_key:
        try:
            from pallas.product.llm.llm_daily_stats_store import write_day_side

            old = _snapshot_locked(day_override=_day_key)
            write_day_side(_day_key, "ai", {"rag": old, "day_key": _day_key, "source": "bot"})
        except Exception:
            pass
    _day_key = today
    _hit_count = 0
    _miss_count = 0
    _by_document.clear()
    _by_source.clear()


def record_rag_query_result(
    *,
    hit: bool,
    documents: list[tuple[str, str]] | None = None,
) -> None:
    """查询级记账：有结果 hit+1，空结果 miss+1；命中时再累加文档/来源。"""
    try:
        with _lock:
            rollover_if_needed()
            global _hit_count, _miss_count  # noqa: PLW0603
            if hit:
                _hit_count += 1
                for raw_name, raw_source in documents or []:
                    name = str(raw_name or "").strip() or str(raw_source or "").strip()
                    source = str(raw_source or "").strip()
                    if name:
                        _by_document[name] = int(_by_document.get(name) or 0) + 1
                    if source:
                        _by_source[source] = int(_by_source.get(source) or 0) + 1
            else:
                _miss_count += 1
    except Exception:
        pass


def _snapshot_locked(*, day_override: str | None = None) -> dict[str, Any]:
    hit = int(_hit_count)
    miss = int(_miss_count)
    return {
        "source": "bot",
        "day_key": day_override or _day_key or today_key(),
        "updated_at": time.time(),
        "hit_count": hit,
        "miss_count": miss,
        "hit_rate": _hit_rate(hit, miss),
        "by_document": dict(_by_document),
        "by_source": dict(_by_source),
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


def merge_llm_rag_snapshots(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hit_count = 0
    miss_count = 0
    by_document: dict[str, int] = {}
    by_source: dict[str, int] = {}
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
        hit_count += int(row.get("hit_count") or 0)
        miss_count += int(row.get("miss_count") or 0)
        docs = row.get("by_document")
        if isinstance(docs, dict):
            for key, value in docs.items():
                name = str(key or "").strip()
                if not name:
                    continue
                by_document[name] = int(by_document.get(name) or 0) + int(value or 0)
        sources = row.get("by_source")
        if isinstance(sources, dict):
            for key, value in sources.items():
                sid = str(key or "").strip()
                if not sid:
                    continue
                by_source[sid] = int(by_source.get(sid) or 0) + int(value or 0)
    return {
        "source": source or "bot",
        "day_key": day_key or today_key(),
        "updated_at": updated_at or time.time(),
        "hit_count": hit_count,
        "miss_count": miss_count,
        "hit_rate": _hit_rate(hit_count, miss_count),
        "by_document": by_document,
        "by_source": by_source,
    }


def llm_rag_metrics_snapshot(*, include_persisted: bool = True) -> dict[str, Any]:
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
        "hit_count": int(persisted_raw.get("hit_count") or 0),
        "miss_count": int(persisted_raw.get("miss_count") or 0),
        "hit_rate": float(persisted_raw.get("hit_rate") or 0),
        "by_document": (
            persisted_raw.get("by_document") if isinstance(persisted_raw.get("by_document"), dict) else {}
        ),
        "by_source": persisted_raw.get("by_source") if isinstance(persisted_raw.get("by_source"), dict) else {},
    }
    local_has = int(local.get("hit_count") or 0) > 0 or int(local.get("miss_count") or 0) > 0
    if not local_has:
        return merge_llm_rag_snapshots([persisted]) if persisted.get("day_key") else local
    return merge_llm_rag_snapshots([persisted, local])


def cluster_llm_rag_metrics_snapshot(*, max_stale_sec: float = 300.0) -> dict[str, Any]:
    rows = [llm_rag_metrics_snapshot(include_persisted=True)]
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_hub():
            from pallas.core.platform.shard.console_stats import iter_worker_shard_ids, read_worker_stats_file

            for shard_id in iter_worker_shard_ids(max_stale_sec=max_stale_sec):
                blob = read_worker_stats_file(shard_id)
                rag = blob.get("llm_rag")
                if not isinstance(rag, dict):
                    continue
                if int(rag.get("hit_count") or 0) <= 0 and int(rag.get("miss_count") or 0) <= 0:
                    continue
                rows.append(rag)
    except Exception:
        pass
    if len(rows) <= 1:
        out = rows[0]
        if isinstance(out, dict):
            return {**out, "source": "bot_cluster" if len(rows) > 1 else out.get("source") or "bot"}
        return out
    merged = merge_llm_rag_snapshots(rows)
    merged["source"] = "bot_cluster"
    return merged


def flush_rag_stats_sync() -> None:
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if shard_ctx.sharding_active() and shard_ctx.is_worker():
            return
        snapshot = (
            cluster_llm_rag_metrics_snapshot()
            if shard_ctx.sharding_active() and shard_ctx.is_hub()
            else llm_rag_metrics_snapshot(include_persisted=True)
        )
    except Exception:
        snapshot = llm_rag_metrics_snapshot(include_persisted=True)
    if int(snapshot.get("hit_count") or 0) <= 0 and int(snapshot.get("miss_count") or 0) <= 0:
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
            {"rag": snapshot, "day_key": snapshot.get("day_key"), "source": "bot"},
        )
    except Exception:
        pass


def clear_llm_rag_metrics_for_tests() -> None:
    global _day_key, _hit_count, _miss_count  # noqa: PLW0603
    with _lock:
        _day_key = ""
        _hit_count = 0
        _miss_count = 0
        _by_document.clear()
        _by_source.clear()
