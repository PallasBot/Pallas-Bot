"""多 Bot / 多进程：同一条群消息仅一只牛抢占处理权。"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from operator import itemgetter
from pathlib import Path

from pallas.core.foundation.paths import plugin_data_dir

_CLAIM_MAX_AGE_SEC = 86400
_PRUNE_MAX_FILES = 500
_PRUNE_MIN_INTERVAL_SEC = 120.0
_PRUNE_FORCE_ENTRY_COUNT = 2500

_claim_roots_ready: set[str] = set()
_last_prune_at: dict[str, float] = {}
# 新建 claim 时递增；prune 后按扫描结果校正，避免限频期间每条消息 scandir 计数
_claim_file_estimate: defaultdict[str, int] = defaultdict(int)


def _sharding_requires_redis() -> bool:
    from pallas.core.platform.coord.redis_settings import sharding_requires_coord_redis

    return sharding_requires_coord_redis()


def _claim_root(plugin: str) -> Path:
    root = plugin_data_dir(plugin) / "message_claims"
    if plugin not in _claim_roots_ready:
        root.mkdir(parents=True, exist_ok=True)
        _claim_roots_ready.add(plugin)
    return root


def _claim_file_path(plugin: str, group_id: int, message_id: int) -> Path:
    return plugin_data_dir(plugin) / "message_claims" / f"{group_id}_{message_id}.claim"


def _claim_path(plugin: str, group_id: int, message_id: int) -> Path:
    return _claim_root(plugin) / f"{group_id}_{message_id}.claim"


def _note_claim_file_created(plugin: str) -> None:
    _claim_file_estimate[plugin] += 1


def _maybe_prune_old_claims(plugin: str) -> None:
    now = time.monotonic()
    last = _last_prune_at.get(plugin, 0.0)
    if now - last < _PRUNE_MIN_INTERVAL_SEC and _claim_file_estimate[plugin] < _PRUNE_FORCE_ENTRY_COUNT:
        return
    _last_prune_at[plugin] = now
    remaining = _prune_old_claims(plugin, max_files=_PRUNE_MAX_FILES)
    _claim_file_estimate[plugin] = remaining


def _prune_old_claims(plugin: str, *, max_files: int = _PRUNE_MAX_FILES) -> int:
    root = plugin_data_dir(plugin) / "message_claims"
    if not root.is_dir():
        return 0
    now = time.time()
    ranked: list[tuple[float, Path]] = []
    try:
        with os.scandir(root) as scan:
            for entry in scan:
                if not entry.is_file() or not entry.name.endswith(".claim"):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                ranked.append((mtime, Path(entry.path)))
    except OSError:
        return 0

    if len(ranked) <= max_files:
        kept = len(ranked)
        for mtime, path in ranked:
            if now - mtime > _CLAIM_MAX_AGE_SEC:
                try:
                    path.unlink(missing_ok=True)
                    kept -= 1
                except OSError:
                    pass
        return max(kept, 0)

    ranked.sort(key=itemgetter(0), reverse=True)
    kept = max_files
    for mtime, path in ranked[max_files:]:
        if now - mtime > _CLAIM_MAX_AGE_SEC:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            kept += 1
    return kept


def read_claim_owner_sync(plugin: str, group_id: int, message_id: int) -> int | None:
    from pallas.core.platform.coord.redis_claim import read_claim_owner_redis_sync

    owner = read_claim_owner_redis_sync(plugin, group_id, message_id)
    if owner is not None:
        return owner
    if _sharding_requires_redis():
        return None
    path = _claim_file_path(plugin, group_id, message_id)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def try_claim_message_sync(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
    from pallas.core.platform.coord.redis_claim import try_claim_message_redis_sync

    redis_result = try_claim_message_redis_sync(plugin, group_id, message_id, bot_id)
    if redis_result is not None:
        return redis_result
    if _sharding_requires_redis():
        return False
    path = _claim_path(plugin, group_id, message_id)
    if path.is_file():
        try:
            return int(path.read_text(encoding="utf-8").strip()) == bot_id
        except (ValueError, OSError):
            return False
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(bot_id).encode("utf-8"))
        finally:
            os.close(fd)
        _note_claim_file_created(plugin)
        _maybe_prune_old_claims(plugin)
        return True
    except FileExistsError:
        try:
            return int(path.read_text(encoding="utf-8").strip()) == bot_id
        except (ValueError, OSError):
            return False


def take_claim_message_sync(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
    from pallas.core.platform.coord.redis_claim import take_claim_message_redis_sync

    redis_result = take_claim_message_redis_sync(plugin, group_id, message_id, bot_id)
    if redis_result is not None:
        return redis_result
    if _sharding_requires_redis():
        return False
    path = _claim_path(plugin, group_id, message_id)
    try:
        path.write_text(str(int(bot_id)), encoding="utf-8")
    except OSError:
        return False
    _note_claim_file_created(plugin)
    _maybe_prune_old_claims(plugin)
    return True


async def try_claim_message(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
    return await asyncio.to_thread(try_claim_message_sync, plugin, group_id, message_id, bot_id)


async def take_claim_message(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
    return await asyncio.to_thread(take_claim_message_sync, plugin, group_id, message_id, bot_id)
