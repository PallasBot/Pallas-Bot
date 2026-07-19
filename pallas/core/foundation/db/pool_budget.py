"""PostgreSQL 连接池预算：为后台任务与远程 I/O 提供背压，避免挤占接话热路径。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pallas.core.foundation.config.repo_settings import repo_env_raw_value, repo_settings_disk_revision

_POOL_SNAPSHOT_TTL_SEC = 0.12
_capacity_cache: int | None = None
_capacity_rev: tuple[tuple[int, int], ...] | None = None
_snapshot_cache: dict[str, int] | None = None
_snapshot_at: float = 0.0


def clear_pool_budget_runtime_cache() -> None:
    global _capacity_cache, _capacity_rev, _snapshot_cache, _snapshot_at
    _capacity_cache = None
    _capacity_rev = None
    _snapshot_cache = None
    _snapshot_at = 0.0


def pg_pool_capacity() -> int:
    global _capacity_cache, _capacity_rev
    rev = repo_settings_disk_revision()
    if _capacity_cache is not None and _capacity_rev == rev:
        return _capacity_cache

    def cfg(key: str, default: str) -> int:
        raw = repo_env_raw_value(key)
        try:
            return int(str(raw if raw is not None else default).strip())
        except ValueError:
            return int(default)

    capacity = cfg("PG_POOL_SIZE", "10") + cfg("PG_MAX_OVERFLOW", "20")
    _capacity_cache = capacity
    _capacity_rev = rev
    return capacity


def pg_pool_snapshot() -> dict[str, int] | None:
    global _snapshot_cache, _snapshot_at
    now = time.monotonic()
    if _snapshot_cache is not None and (now - _snapshot_at) < _POOL_SNAPSHOT_TTL_SEC:
        return _snapshot_cache
    from pallas.core.foundation.db.repository_pg import pg_pool_live_stats

    snap = pg_pool_live_stats()
    _snapshot_cache = snap
    _snapshot_at = now
    return snap


def pg_pool_checked_out() -> int | None:
    snap = pg_pool_snapshot()
    if snap is None:
        return None
    return int(snap.get("checked_out", 0))


def pg_pool_utilization() -> float | None:
    snap = pg_pool_snapshot()
    if snap is None:
        return None
    capacity = int(snap.get("capacity", 0))
    if capacity <= 0:
        return None
    return float(snap.get("checked_out", 0)) / float(capacity)


def pg_pool_under_pressure(*, threshold: float = 0.75) -> bool:
    util = pg_pool_utilization()
    if util is None:
        return False
    return util >= threshold


def is_pg_pool_timeout_error(exc: BaseException) -> bool:
    """SQLAlchemy QueuePool 等待连接超时等，接话热路径应快速放弃而非占满 matcher 墙钟。"""
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    exc_type = type(exc)
    if exc_type.__module__.startswith("sqlalchemy") and exc_type.__name__ == "TimeoutError":
        return True
    msg = str(exc)
    return "QueuePool limit" in msg or "connection timed out" in msg


def cap_by_pg_pool(requested: int, *, workload_fraction: float = 0.30) -> int:
    """按池容量上限裁剪后台并发。"""
    capacity = pg_pool_capacity()
    frac = max(0.05, min(0.90, float(workload_fraction)))
    ceiling = max(1, int(capacity * frac))
    return max(1, min(int(requested), ceiling))


def remote_corpus_concurrency_limit() -> int:
    raw = repo_env_raw_value("PALLAS_CORPUS_REMOTE_MAX_CONCURRENT")
    if raw is not None:
        try:
            return max(1, min(64, int(str(raw).strip())))
        except ValueError:
            pass
    return max(2, pg_pool_capacity() // 10)


def pool_budget_status() -> dict[str, Any]:
    snap = pg_pool_snapshot()
    capacity = pg_pool_capacity()
    util = pg_pool_utilization()
    return {
        "capacity": capacity,
        "live": snap,
        "utilization": util,
        "under_pressure": util is not None and util >= 0.75,
        "remote_corpus_limit": remote_corpus_concurrency_limit(),
    }
