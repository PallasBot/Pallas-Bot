"""分片 coord 共享 Redis JSON 读写、WATCH/MULTI 变更与键扫描。"""

from __future__ import annotations

import json
from typing import Any

from redis.exceptions import WatchError


def safe_key_part(raw: str | int) -> str:
    s = str(raw)
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def coord_key(namespace: str, *parts: str | int) -> str:
    safe = [safe_key_part(p) for p in parts]
    return f"pallas:coord:{namespace}:" + ":".join(safe)


def redis_client_or_none():
    from src.platform.coord.redis_claim import get_coord_redis_client
    from src.platform.coord.redis_settings import coord_redis_enabled

    if not coord_redis_enabled():
        return None
    return get_coord_redis_client()


def read_json_sync(key: str) -> dict[str, Any] | None:
    client = redis_client_or_none()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def setex_json_sync(key: str, data: dict[str, Any], ttl_sec: int) -> bool:
    client = redis_client_or_none()
    if client is None:
        return False
    ttl = max(1, int(ttl_sec))
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    try:
        client.setex(key, ttl, body)
        return True
    except Exception:
        return False


def store_json_sync(
    key: str,
    data: dict[str, Any],
    *,
    ttl_sec: int,
    wake_channel: str | None = None,
    wake_body: dict[str, Any] | None = None,
) -> bool:
    client = redis_client_or_none()
    if client is None:
        return False
    ttl = max(1, int(ttl_sec))
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    try:
        pipe = client.pipeline(transaction=True)
        pipe.setex(key, ttl, body)
        if wake_channel and wake_body is not None:
            wake = json.dumps(wake_body, ensure_ascii=False, separators=(",", ":"))
            pipe.publish(wake_channel, wake)
        pipe.execute()
        return True
    except Exception:
        return False


def mutate_json_sync(
    key: str,
    mutator,
    *,
    ttl_sec_fn,
    create_if_missing: bool = True,
    retries: int = 8,
) -> dict[str, Any] | None:
    client = redis_client_or_none()
    if client is None:
        return None
    for _ in range(max(1, retries)):
        try:
            with client.pipeline() as pipe:
                pipe.watch(key)
                raw = client.get(key)
                if raw is None:
                    if not create_if_missing:
                        pipe.unwatch()
                        return None
                    data: dict[str, Any] = {}
                else:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        return None
                    data = parsed
                mutator(data)
                ttl = max(1, int(ttl_sec_fn(data)))
                encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                pipe.multi()
                pipe.setex(key, ttl, encoded)
                pipe.execute()
                return data
        except WatchError:
            continue
        except Exception:
            return None
    return None


def delete_key_sync(key: str) -> bool:
    client = redis_client_or_none()
    if client is None:
        return False
    try:
        client.delete(key)
        return True
    except Exception:
        return False


def scan_keys_sync(prefix: str) -> list[str]:
    client = redis_client_or_none()
    if client is None:
        return []
    out: list[str] = []
    cursor = 0
    try:
        while True:
            cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=128)
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                out.append(str(key))
            if cursor == 0:
                break
    except Exception:
        return out
    return out
