"""分片 worker 在线状态：Redis HASH。"""

from __future__ import annotations

import json
import time
from typing import Any

from pallas.core.platform.shard import context as shard_ctx

_HASH_KEY = "pallas:presence:bots"
_UPDATED_AT_KEY = "pallas:presence:updated_at"
_FILE_IMPORTED_KEY = "pallas:presence:file_imported"


def presence_uses_redis_only() -> bool:
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if shard_ctx.sharding_active():
        return True
    return coord_redis_enabled() and get_coord_redis_client() is not None


def get_presence_redis_client():
    from pallas.core.platform.coord.redis_claim import get_coord_redis_client
    from pallas.core.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return None
    return get_coord_redis_client()


def _decode_rec(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _encode_rec(rec: dict[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))


def _touch_updated_at(client) -> None:
    try:
        client.set(_UPDATED_AT_KEY, str(time.time()))
    except Exception:
        pass


def import_file_presence_to_redis_sync(file_bots: dict[str, dict[str, Any]]) -> bool:
    """Redis 为空时一次性导入磁盘 presence，避免切换存储后在线列表短暂空白。"""
    client = get_presence_redis_client()
    if client is None or not file_bots:
        return False
    try:
        if client.hlen(_HASH_KEY) > 0:
            return True
        if client.get(_FILE_IMPORTED_KEY):
            return True
        pipe = client.pipeline()
        for key, rec in file_bots.items():
            if isinstance(rec, dict):
                pipe.hset(_HASH_KEY, str(key), _encode_rec(rec))
        pipe.set(_FILE_IMPORTED_KEY, "1")
        pipe.set(_UPDATED_AT_KEY, str(time.time()))
        pipe.execute()
        return True
    except Exception:
        return False


def read_presence_bots_redis_sync() -> dict[str, dict[str, Any]] | None:
    """返回 None 表示未走 Redis。"""
    client = get_presence_redis_client()
    if client is None:
        return None
    try:
        raw_map = client.hgetall(_HASH_KEY)
        if not raw_map:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for key, val in raw_map.items():
            k = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            rec = _decode_rec(val)
            if rec is not None:
                out[k] = rec
        return out
    except Exception:
        return None


def note_worker_bot_connected_redis_sync(
    *,
    qq: int,
    connection_key: str,
    adapter: str,
    shard_id: int,
    nickname: str = "",
) -> bool:
    client = get_presence_redis_client()
    if client is None:
        return False
    key = str(int(qq))
    now = time.time()
    rec = {
        "qq": int(qq),
        "shard_id": int(shard_id),
        "connection_key": connection_key,
        "adapter": adapter,
        "connected_at_unix": int(now),
        "last_seen_at": now,
        "nickname": (nickname or "").strip(),
    }
    try:
        client.hset(_HASH_KEY, key, _encode_rec(rec))
        client.setnx(_FILE_IMPORTED_KEY, "1")
        _touch_updated_at(client)
        return True
    except Exception:
        return False


def touch_worker_bot_presence_redis_sync(*, qq: int) -> bool:
    client = get_presence_redis_client()
    if client is None:
        return False
    key = str(int(qq))
    try:
        raw = client.hget(_HASH_KEY, key)
        rec = _decode_rec(raw)
        if rec is None:
            return True
        rec["last_seen_at"] = time.time()
        client.hset(_HASH_KEY, key, _encode_rec(rec))
        _touch_updated_at(client)
        return True
    except Exception:
        return False


def note_worker_bot_disconnected_redis_sync(*, qq: int) -> bool:
    client = get_presence_redis_client()
    if client is None:
        return False
    try:
        client.hdel(_HASH_KEY, str(int(qq)))
        _touch_updated_at(client)
        return True
    except Exception:
        return False


def _minimal_presence_rec(*, qq: int, shard_id: int, now: float) -> dict[str, Any]:
    key = str(int(qq))
    return {
        "qq": int(qq),
        "shard_id": int(shard_id),
        "connection_key": key,
        "adapter": "",
        "connected_at_unix": int(now),
        "last_seen_at": now,
        "nickname": "",
    }


def reconcile_local_worker_presence_redis_sync(*, shard_id: int, local_qq_ids: set[int]) -> bool:
    client = get_presence_redis_client()
    if client is None:
        return False
    now = time.time()
    sid = int(shard_id)
    try:
        raw_map = client.hgetall(_HASH_KEY) or {}
        pipe = client.pipeline()
        changed = False
        present_for_shard: set[int] = set()
        for key, val in raw_map.items():
            k = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            rec = _decode_rec(val)
            if rec is None:
                pipe.hdel(_HASH_KEY, k)
                changed = True
                continue
            if int(rec.get("shard_id") or -1) != sid:
                continue
            try:
                qq = int(rec.get("qq") or k)
            except (TypeError, ValueError):
                pipe.hdel(_HASH_KEY, k)
                changed = True
                continue
            if qq not in local_qq_ids:
                pipe.hdel(_HASH_KEY, k)
                changed = True
            else:
                present_for_shard.add(qq)
                rec["last_seen_at"] = now
                pipe.hset(_HASH_KEY, k, _encode_rec(rec))
                changed = True
        for qq in local_qq_ids:
            if qq in present_for_shard:
                continue
            key = str(int(qq))
            pipe.hset(_HASH_KEY, key, _encode_rec(_minimal_presence_rec(qq=qq, shard_id=sid, now=now)))
            changed = True
        if changed:
            pipe.set(_UPDATED_AT_KEY, str(now))
            pipe.execute()
        return True
    except Exception:
        return False


def prune_stale_presence_entries_redis_sync(*, max_age_sec: float) -> int | None:
    """返回 None 表示 Redis 不可用；否则返回删除条数。"""
    client = get_presence_redis_client()
    if client is None:
        return None
    now = time.time()
    removed = 0
    try:
        raw_map = client.hgetall(_HASH_KEY)
        if not raw_map:
            return 0
        pipe = client.pipeline()
        for key, val in raw_map.items():
            k = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            rec = _decode_rec(val)
            if rec is None:
                pipe.hdel(_HASH_KEY, k)
                removed += 1
                continue
            last = float(rec.get("last_seen_at") or rec.get("connected_at_unix") or 0)
            if last <= 0 or now - last > max_age_sec:
                pipe.hdel(_HASH_KEY, k)
                removed += 1
        if removed:
            pipe.set(_UPDATED_AT_KEY, str(now))
            pipe.execute()
        return removed
    except Exception:
        return None
