"""分片：MAA getTask 轮询活跃时间（跨 worker 共享，供 was_seen / 绑定校验）。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from src.common.paths import plugin_data_dir

_PLUGIN = "pallas_shard"
_DEVICE_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_DEVICE_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# getTask 高频轮询时降低每 (user, device) 落盘频率；进程内缓存仍立即更新
_DISK_FLUSH_INTERVAL_SEC = 2.0

_lock = threading.Lock()
_local_seen: dict[tuple[str, str], float] = {}
_last_disk_write: dict[tuple[str, str], float] = {}


def clear_seen_cache_for_tests() -> None:
    """测试用：清空进程内缓存。"""
    with _lock:
        _local_seen.clear()
        _last_disk_write.clear()


def normalize_maa_device_id(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    compact = s.lower().replace("-", "")
    if _DEVICE_HEX32_RE.fullmatch(compact):
        return compact
    if _DEVICE_UUID_RE.fullmatch(s.lower()):
        return compact
    return None


def _cache_key(user: str, device: str) -> tuple[str, str] | None:
    u = (user or "").strip()
    norm = normalize_maa_device_id(device)
    if not u or not norm:
        return None
    return u, norm


def _seen_dir() -> Path:
    root = Path(plugin_data_dir(_PLUGIN, create=True)) / "coord" / "maa_seen"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _seen_path(user: str, device: str) -> Path | None:
    key = _cache_key(user, device)
    if key is None:
        return None
    return _seen_dir() / f"{key[0]}_{key[1]}.json"


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _acquire_lock(lock_path: Path, *, timeout: float = 3.0) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 10.0:
                    lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.02)
    return None


def _release_lock(fd: int | None, lock_path: Path) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_seen_file(path: Path, user: str, device: str, seen_at: float) -> None:
    lk = _lock_path(path)
    fd = _acquire_lock(lk)
    if fd is None:
        return
    try:
        data: dict[str, Any] = {
            "user": (user or "").strip(),
            "device": normalize_maa_device_id(device),
            "seen_at": seen_at,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        _release_lock(fd, lk)


def _read_seen_at_from_disk(path: Path) -> float:
    if not path.is_file():
        return 0.0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not isinstance(raw, dict):
        return 0.0
    return float(raw.get("seen_at") or 0)


def flush_dirty_maa_seen_sync() -> None:
    """将进程内仍有效的 seen 刷入磁盘（清理前调用，避免防抖导致文件过旧被误删）。"""
    now = time.time()
    with _lock:
        snap = dict(_local_seen)
    for key, seen_at in snap.items():
        if seen_at <= 0:
            continue
        user, norm = key
        path = _seen_dir() / f"{user}_{norm}.json"
        _write_seen_file(path, user, norm, seen_at)
        with _lock:
            _last_disk_write[key] = now


def touch_maa_seen_sync(user: str, device: str) -> None:
    key = _cache_key(user, device)
    if key is None:
        return
    now = time.time()
    with _lock:
        _local_seen[key] = now
        last_disk = _last_disk_write.get(key, 0.0)
        need_flush = now - last_disk >= _DISK_FLUSH_INTERVAL_SEC
    if not need_flush:
        return
    path = _seen_path(user, device)
    if path is None:
        return
    _write_seen_file(path, user, device, now)
    with _lock:
        _last_disk_write[key] = now


def was_maa_seen_sync(user: str, device: str, ttl: int) -> bool:
    key = _cache_key(user, device)
    if key is None:
        return False
    ttl_sec = max(1, int(ttl))
    now = time.time()
    with _lock:
        local_at = _local_seen.get(key)
    if local_at and local_at > 0 and now - local_at <= ttl_sec:
        return True
    path = _seen_path(user, device)
    if path is None:
        return False
    seen_at = _read_seen_at_from_disk(path)
    if seen_at <= 0 or now - seen_at > ttl_sec:
        return False
    with _lock:
        if seen_at > _local_seen.get(key, 0.0):
            _local_seen[key] = seen_at
    return True


async def prune_stale_maa_seen_files(*, max_age_sec: float | None = None) -> None:
    """清理过期轮询记录文件（默认与 maa_seen_ttl 同量级）。"""
    from src.plugins.maa.config import get_maa_config

    flush_dirty_maa_seen_sync()
    ttl = float(max_age_sec if max_age_sec is not None else get_maa_config().maa_seen_ttl_seconds)
    root = _seen_dir()
    if not root.is_dir():
        return
    now = time.time()
    with _lock:
        active_keys = {k for k, ts in _local_seen.items() if ts > 0 and now - ts <= ttl}
    for path in root.glob("*.json"):
        try:
            name = path.stem
            if "_" not in name:
                path.unlink(missing_ok=True)
                continue
            user_part, norm_part = name.split("_", 1)
            if (user_part, norm_part) in active_keys:
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            seen_at = float(raw.get("seen_at") or 0) if isinstance(raw, dict) else 0.0
            if seen_at <= 0 or now - seen_at > ttl:
                path.unlink(missing_ok=True)
                with _lock:
                    _local_seen.pop((user_part, norm_part), None)
                    _last_disk_write.pop((user_part, norm_part), None)
        except (OSError, json.JSONDecodeError):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
