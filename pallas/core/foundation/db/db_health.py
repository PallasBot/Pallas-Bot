"""进程内数据库健康状态：供控制台摘要与热路径非关键门禁共用。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

HealthStatus = Literal["healthy", "degraded", "unhealthy"]

_FAIL_STREAK_TO_UNHEALTHY = 2
_OK_STREAK_TO_HEALTHY = 2
_DEGRADED_UTIL_THRESHOLD = 0.75

_status: HealthStatus = "healthy"
_reason: str = ""
_updated_at: float = 0.0
_fail_streak: int = 0
_ok_streak: int = 0
_last_probe_ok: bool | None = None
_pool_summary: dict[str, Any] | None = None


@dataclass(frozen=True)
class DbHealthSnapshot:
    status: HealthStatus
    reason: str
    updated_at: float
    last_probe_ok: bool | None
    pool: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "updated_at": self.updated_at,
            "last_probe_ok": self.last_probe_ok,
            "pool": self.pool,
        }


def reset_db_health_for_tests() -> None:
    global _status, _reason, _updated_at, _fail_streak, _ok_streak, _last_probe_ok, _pool_summary
    _status = "healthy"
    _reason = ""
    _updated_at = 0.0
    _fail_streak = 0
    _ok_streak = 0
    _last_probe_ok = None
    _pool_summary = None


def get_db_health() -> DbHealthSnapshot:
    return DbHealthSnapshot(
        status=_status,
        reason=_reason,
        updated_at=_updated_at,
        last_probe_ok=_last_probe_ok,
        pool=dict(_pool_summary) if _pool_summary is not None else None,
    )


def is_db_unhealthy() -> bool:
    return _status == "unhealthy"


def is_db_degraded() -> bool:
    return _status == "degraded"


def should_skip_noncritical_db() -> bool:
    """消息热路径上非关键读/enrich 在 unhealthy 时跳过。"""
    return _status == "unhealthy"


def note_db_probe_result(
    ok: bool,
    *,
    reason: str = "",
    pool: dict[str, Any] | None = None,
) -> DbHealthSnapshot:
    """记录一次连通性探测结果，按连续成败切换状态。"""
    global _status, _reason, _updated_at, _fail_streak, _ok_streak, _last_probe_ok, _pool_summary

    _last_probe_ok = bool(ok)
    _updated_at = time.time()
    if pool is not None:
        _pool_summary = dict(pool)

    if ok:
        _fail_streak = 0
        _ok_streak += 1
        if _status == "unhealthy" and _ok_streak >= _OK_STREAK_TO_HEALTHY:
            _status = "healthy"
            _reason = reason or "连通恢复"
        elif _status != "unhealthy":
            util = None
            if _pool_summary is not None:
                util = _pool_summary.get("utilization")
            if isinstance(util, (int, float)) and float(util) >= _DEGRADED_UTIL_THRESHOLD:
                _status = "degraded"
                _reason = reason or "连接池利用率偏高"
            else:
                _status = "healthy"
                _reason = reason or ""
        return get_db_health()

    _ok_streak = 0
    _fail_streak += 1
    if _fail_streak >= _FAIL_STREAK_TO_UNHEALTHY:
        _status = "unhealthy"
        _reason = reason or "连通探测失败"
    elif _status != "unhealthy":
        _status = "degraded"
        _reason = reason or "连通探测失败"
    return get_db_health()


def note_db_pool_pressure(
    *,
    under_pressure: bool,
    pool: dict[str, Any] | None = None,
    reason: str = "",
) -> DbHealthSnapshot:
    """池压力只影响 healthy↔degraded，不直接标 unhealthy。"""
    global _status, _reason, _updated_at, _pool_summary

    if pool is not None:
        _pool_summary = dict(pool)
    _updated_at = time.time()

    if _status == "unhealthy":
        return get_db_health()

    if under_pressure:
        _status = "degraded"
        _reason = reason or "连接池压力偏高"
    elif _status == "degraded" and not reason:
        # 压力解除且无额外原因时回到 healthy
        _status = "healthy"
        _reason = ""
    return get_db_health()


async def probe_runtime_db_health() -> DbHealthSnapshot:
    """对当前运行时后端做短探测，并更新进程内状态。"""
    from pallas.core.foundation.db import get_db_backend, is_mongodb_backend, is_postgresql_backend
    from pallas.core.foundation.db.pool_budget import pool_budget_status

    backend = (get_db_backend() or "").lower()
    pool: dict[str, Any] | None = None
    if is_postgresql_backend(backend):
        budget = pool_budget_status()
        pool = {
            "capacity": budget.get("capacity"),
            "utilization": budget.get("utilization"),
            "under_pressure": budget.get("under_pressure"),
            "live": budget.get("live"),
        }
        try:
            from sqlalchemy import text

            from pallas.core.foundation.db.repository_pg import is_pg_initialized, pg_engine

            if not is_pg_initialized() or pg_engine() is None:
                return note_db_probe_result(False, reason="PostgreSQL 未就绪", pool=pool)
            engine = pg_engine()
            assert engine is not None
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            snap = note_db_probe_result(True, pool=pool)
            if budget.get("under_pressure"):
                return note_db_pool_pressure(under_pressure=True, pool=pool)
            return snap
        except Exception as e:  # noqa: BLE001
            return note_db_probe_result(False, reason=f"PostgreSQL 探测失败: {e}", pool=pool)

    if is_mongodb_backend(backend):
        try:
            from pallas.core.foundation.db.modules import BotConfigModule

            coll = BotConfigModule.get_pymongo_collection()
            client = coll.database.client
            await client.admin.command("ping")
            return note_db_probe_result(True)
        except Exception as e:  # noqa: BLE001
            return note_db_probe_result(False, reason=f"MongoDB 探测失败: {e}")

    return note_db_probe_result(False, reason=f"未知后端: {backend or 'empty'}")
