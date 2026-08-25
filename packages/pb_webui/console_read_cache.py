"""控制台扩展 JSON 读缓存。"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import time
import typing
from pathlib import Path
from typing import Any

from nonebot import logger

from pallas.core.foundation.fs_lock import atomic_write_text
from pallas.core.foundation.paths import plugin_data_dir

_READ_CACHE: dict[str, dict[str, Any]] = {}
_READ_INFLIGHT: dict[str, asyncio.Task[Any]] = {}

_FILE_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def clear_extended_read_cache() -> None:
    """清空控制台扩展 JSON 的进程内读缓存。"""
    _READ_CACHE.clear()
    for task in list(_READ_INFLIGHT.values()):
        if not task.done():
            task.cancel()
    _READ_INFLIGHT.clear()


def cache_value_copy(data: Any) -> Any:
    """避免调用方就地修改 dict/list 污染缓存条目。"""
    if isinstance(data, (dict, list)):
        try:
            return copy.deepcopy(data)
        except Exception:  # noqa: BLE001
            return data
    return data


def format_stale_window(stale_sec: float) -> str:
    """把 stale_sec 写成维护者可读的时间窗口。"""
    if stale_sec >= 60:
        minutes = stale_sec / 60.0
        text = f"{minutes:.0f}" if minutes >= 10 else f"{minutes:.1f}".rstrip("0").rstrip(".")
        return f"约 {text} 分钟"
    return f"约 {stale_sec:.0f} 秒"


def format_cache_fallback_warning(*, key: str, stale_sec: float, err: Exception) -> str:
    """缓存兜底 warn 文案：说明失败与可用缓存窗口，并保留 key 便于排查。"""
    window = format_stale_window(stale_sec)
    if key.startswith("update_check_"):
        if key.endswith(":False"):
            token_hint = "；未配置 GitHub token"
        elif key.endswith(":True"):
            token_hint = "；已配置 GitHub token"
        else:
            token_hint = ""
        return (
            f"[WebUI] Update check request failed; using cached result from the previous [{window}]{token_hint}. "
            f"Cache key: [{key}]. Error: [{err}]"
        )
    return f"[WebUI] Read failed; using cached result from the previous [{window}]. Cache key: [{key}]. Error: [{err}]"


def _snapshot_dir_path(*, create: bool) -> Path:
    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir)
        if create:
            root.mkdir(parents=True, exist_ok=True)
        base = root / "pb_webui"
    else:
        base = plugin_data_dir("pb_webui", create=create)
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base / "console_read_snapshots"


def _snapshot_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe = _FILE_SAFE.sub("_", key)[:80] or "x"
    return _snapshot_dir_path(create=False) / f"{digest}-{safe}.json"


def _read_snapshot(key: str) -> Any | None:
    """读磁盘快照；缺失或损坏时返回 None。"""
    try:
        snapshot = _snapshot_path(key)
        if not snapshot.is_file():
            return None
        with snapshot.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def _write_snapshot(key: str, data: Any) -> None:
    """原子写入磁盘快照；失败只警告不抛出。"""
    try:
        snapshot = _snapshot_path(key)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(data, ensure_ascii=False)
        atomic_write_text(snapshot, body)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("[WebUI] Failed to persist read snapshot for key [{}]: [{}]", key, exc)


async def cached_read(
    *,
    key: str,
    loader: typing.Callable[[], typing.Awaitable[Any]],
    ttl_sec: float = 1.0,
    stale_sec: float = 20.0,
    swr: bool = False,
    persist_snapshot: bool = False,
) -> Any:
    """短 TTL 读缓存；失败时回退最近成功快照。swr 时过期即回退快照并在后台刷新。"""
    now = time.monotonic()
    hit = _READ_CACHE.get(key)
    if hit and now < float(hit["exp"]):
        return await asyncio.to_thread(cache_value_copy, hit["data"])

    inflight = _READ_INFLIGHT.get(key)
    if inflight is not None and not inflight.done():
        return await inflight

    if swr:
        stale_data = hit["data"] if hit is not None else None
        if stale_data is None and persist_snapshot:
            stale_data = await asyncio.to_thread(_read_snapshot, key)
        if stale_data is not None:
            background = _READ_INFLIGHT.get(key)
            if background is None or background.done():
                _spawn_background_refresh(key, loader, ttl_sec, stale_sec, persist_snapshot)
            return await asyncio.to_thread(cache_value_copy, stale_data)

    task = asyncio.create_task(
        _load_and_store(key, loader, ttl_sec, stale_sec, persist_snapshot, swallow=False, swr=swr)
    )
    _READ_INFLIGHT[key] = task
    try:
        return await task
    finally:
        _READ_INFLIGHT.pop(key, None)


async def _load_and_store(
    key: str,
    loader: typing.Callable[[], typing.Awaitable[Any]],
    ttl_sec: float,
    stale_sec: float,
    persist_snapshot: bool,
    *,
    swallow: bool,
    swr: bool,
) -> Any:
    stale_hit = _READ_CACHE.get(key)
    try:
        data = await loader()
    except Exception as exc:  # noqa: BLE001
        if stale_hit is not None and time.monotonic() < float(stale_hit["stale_exp"]):
            logger.warning(format_cache_fallback_warning(key=key, stale_sec=stale_sec, err=exc))
            return await asyncio.to_thread(cache_value_copy, stale_hit["data"])
        if swallow:
            logger.warning("[WebUI] Background refresh failed for key [{}]: [{}]", key, exc)
            stale = await asyncio.to_thread(cache_value_copy, stale_hit["data"]) if stale_hit is not None else None
            return stale
        raise
    stored = await asyncio.to_thread(cache_value_copy, data)
    cached_at = time.monotonic()
    ttl_base = max(0.05, ttl_sec) if not swr else ttl_sec
    _READ_CACHE[key] = {
        "data": stored,
        "exp": cached_at + ttl_base,
        "stale_exp": cached_at + max(ttl_sec, stale_sec),
    }
    if persist_snapshot:
        await asyncio.to_thread(_write_snapshot, key, stored)
    return await asyncio.to_thread(cache_value_copy, stored)


def _spawn_background_refresh(
    key: str,
    loader: typing.Callable[[], typing.Awaitable[Any]],
    ttl_sec: float,
    stale_sec: float,
    persist_snapshot: bool,
) -> None:
    async def run() -> None:
        try:
            await _load_and_store(key, loader, ttl_sec, stale_sec, persist_snapshot, swallow=True, swr=True)
        finally:
            _READ_INFLIGHT.pop(key, None)

    task = asyncio.create_task(run())
    _READ_INFLIGHT[key] = task


def drop_read_cache(prefixes: tuple[str, ...]) -> None:
    if _READ_CACHE:
        for k in [k for k in _READ_CACHE if any(k.startswith(p) for p in prefixes)]:
            _READ_CACHE.pop(k, None)
    snapshot_dir = _snapshot_dir_path(create=False)
    if not snapshot_dir.is_dir():
        return
    for snapshot in snapshot_dir.glob("*.json"):
        filename = snapshot.name
        dash = filename.find("-")
        if dash < 0:
            continue
        safe_key = filename[dash + 1 :]
        if any(safe_key.startswith(_FILE_SAFE.sub("_", p)) for p in prefixes):
            try:
                snapshot.unlink(missing_ok=True)
            except OSError:
                pass
