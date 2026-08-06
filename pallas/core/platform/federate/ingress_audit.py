"""联邦 ingress 的无正文终态计数。"""

from __future__ import annotations

import asyncio
from collections import Counter

from pallas.core.platform.federate.config import federate_redis_prefix
from pallas.core.platform.federate.redis_settings import get_federate_redis_client

_AUDIT_KEY_SEGMENT = "ingress_audit"
_AUDIT_TTL_SEC = 300
_AUDIT_FLUSH_DELAY_SEC = 0.5
_pending_audit_counts: Counter[str] = Counter()
_audit_flush_task: asyncio.Task[None] | None = None


def record_federate_ingress_audit(*, capability: str | None, outcome: str) -> None:
    """在 ingress 内存中聚合终态；Redis I/O 由延迟任务批量完成。"""
    global _audit_flush_task
    kind = str(capability or "none").strip() or "none"
    state = str(outcome).strip()
    if not state:
        return
    _pending_audit_counts[f"{kind}:{state}"] += 1
    if _audit_flush_task is not None and not _audit_flush_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _audit_flush_task = loop.create_task(_flush_federate_ingress_audit_after_delay())


async def _flush_federate_ingress_audit_after_delay() -> None:
    await asyncio.sleep(_AUDIT_FLUSH_DELAY_SEC)
    await flush_federate_ingress_audit()


async def flush_federate_ingress_audit() -> None:
    if not _pending_audit_counts:
        return
    counts = dict(_pending_audit_counts)
    _pending_audit_counts.clear()
    try:
        await asyncio.to_thread(write_federate_ingress_audit_counts_sync, counts)
    except Exception:
        _pending_audit_counts.update(counts)


def write_federate_ingress_audit_counts_sync(counts: dict[str, int]) -> None:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    if client is None or not prefix:
        return
    key = f"{prefix}:{_AUDIT_KEY_SEGMENT}"
    try:
        pipe = client.pipeline()
        for field, count in counts.items():
            pipe.hincrby(key, field, int(count))
        pipe.expire(key, _AUDIT_TTL_SEC)
        pipe.execute()
    except Exception:
        raise


def reset_federate_ingress_audit_for_tests() -> None:
    global _audit_flush_task
    _pending_audit_counts.clear()
    if _audit_flush_task is not None and not _audit_flush_task.done():
        _audit_flush_task.cancel()
    _audit_flush_task = None


def federate_ingress_audit_summary_sync() -> dict[str, int]:
    client = get_federate_redis_client()
    prefix = federate_redis_prefix()
    if client is None or not prefix:
        return {}
    try:
        raw = client.hgetall(f"{prefix}:{_AUDIT_KEY_SEGMENT}")
    except Exception:
        return {}
    result: dict[str, int] = {}
    for raw_key, raw_value in (raw or {}).items():
        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
        try:
            result[f"federate_ingress_{key}"] = int(raw_value)
        except (TypeError, ValueError):
            continue
    return result
