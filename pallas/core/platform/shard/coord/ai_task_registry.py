"""AI 异步任务持久化登记；分片模式额外记录 callback 所属 worker 路由。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from pallas.core.platform.coord.redis_claim import log_coord_redis_failure
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.registry import get_shard_registry, worker_port_for_shard
from pallas.core.platform.shard.registry.config import get_shard_registry_settings
from pallas.core.platform.shard.registry.store import assign_bot_to_shard
from pallas.core.platform.shard.worker_port import current_worker_port

_DEFAULT_TTL_SEC = 86400.0
_KEY_PREFIX = "pallas:ai_task:"


def ai_task_ttl_sec() -> float:
    raw = os.getenv("PALLAS_AI_TASK_TTL_SEC", "").strip()
    try:
        ttl = float(raw) if raw else _DEFAULT_TTL_SEC
    except ValueError:
        ttl = _DEFAULT_TTL_SEC
    return max(600.0, ttl)


def ai_task_redis_key(task_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)
    return f"{_KEY_PREFIX}{safe}"


def write_ai_task_redis_sync(rec: dict[str, Any], *, ttl_sec: int) -> bool:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return False
    client = get_coord_redis_client()
    if client is None:
        return False
    task_id = str(rec.get("task_id") or "").strip()
    if not task_id:
        return False
    try:
        body = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        client.set(ai_task_redis_key(task_id), body, ex=max(60, int(ttl_sec)))
        return True
    except Exception as e:
        log_coord_redis_failure("write_ai_task", e)
        return False


def read_ai_task_redis_sync(task_id: str) -> dict[str, Any] | None:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return None
    client = get_coord_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(ai_task_redis_key(task_id))
    except Exception as e:
        log_coord_redis_failure("read_ai_task", e)
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def remove_ai_task_redis_sync(task_id: str) -> None:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return
    client = get_coord_redis_client()
    if client is None:
        return
    try:
        client.delete(ai_task_redis_key(task_id))
    except Exception as e:
        log_coord_redis_failure("remove_ai_task", e)


def claim_ai_task_redis_sync(task_id: str) -> dict[str, Any] | None:
    """原子读取并删除 Redis 中的 AI 任务登记。"""
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return None
    client = get_coord_redis_client()
    if client is None:
        return None
    key = ai_task_redis_key(task_id)
    try:
        getdel = getattr(client, "getdel", None)
        if callable(getdel):
            raw = getdel(key)
        else:
            raw = client.get(key)
            if raw is not None:
                client.delete(key)
    except Exception as e:
        log_coord_redis_failure("claim_ai_task", e)
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_stale(rec: dict[str, Any]) -> bool:
    start = float(rec.get("start_time") or 0)
    return start <= 0 or (time.time() - start) > ai_task_ttl_sec()


def build_ai_task_record(task_id: str, task_status: dict[str, Any]) -> dict[str, Any] | None:
    bot_raw = task_status.get("bot_id")
    if bot_raw is None:
        return None
    bot_id = str(bot_raw).strip()
    if not bot_id.isdigit():
        return None
    try:
        record = json.loads(json.dumps(task_status, ensure_ascii=False))
        start_time = float(task_status.get("start_time") or time.time())
    except (TypeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    record.update(task_id=task_id, bot_id=bot_id, start_time=start_time)
    if not shard_ctx.sharding_active():
        return record
    reg = get_shard_registry()
    sid = reg.shard_for_bot(bot_id)
    if sid is not None:
        port = worker_port_for_shard(int(sid), registry=reg)
    else:
        local_port = current_worker_port()
        if local_port is not None:
            sid = int(get_shard_registry_settings().shard_id)
            port = int(local_port)
        else:
            sid = assign_bot_to_shard(bot_id, registry=reg)
            if sid is None:
                return None
            port = worker_port_for_shard(int(sid), registry=reg)
    record.update(shard_id=int(sid), worker_port=int(port))
    return record


def register_ai_task(task_id: str, task_status: dict[str, Any]) -> None:
    rec = build_ai_task_record(task_id, task_status)
    if rec is None:
        return
    ttl = int(ai_task_ttl_sec())
    write_ai_task_redis_sync(rec, ttl_sec=ttl)


def remove_ai_task(task_id: str) -> None:
    remove_ai_task_redis_sync(task_id)


def get_ai_task_record(task_id: str) -> dict[str, Any] | None:
    rec = read_ai_task_redis_sync(task_id)
    if not rec or _is_stale(rec):
        remove_ai_task(task_id)
        return None
    return rec


def claim_ai_task_record(task_id: str) -> dict[str, Any] | None:
    """原子领取持久化任务登记；已被领取或过期则返回 None。"""
    rec = claim_ai_task_redis_sync(task_id)
    if not rec:
        return None
    if _is_stale(rec):
        return None
    return rec


def resolve_worker_port_for_task(task_id: str) -> int | None:
    rec = get_ai_task_record(task_id)
    if not rec:
        return None
    try:
        return int(rec["worker_port"])
    except (KeyError, TypeError, ValueError):
        return None
