"""分片 worker 控制台指标落盘（今日次数、单次耗时、matcher 时间桶）；hub 读取合并。"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import is_sharding_active

_PLUGIN = "pallas_shard"
_STATS_DIR = "stats"
_STORE_VER = 1
_WORKER_FILE_RE = re.compile(r"^worker-(\d+)\.json$")


def stats_dir():
    d = plugin_data_dir(_PLUGIN, create=True) / _STATS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def worker_stats_path(shard_id: int):
    return stats_dir() / f"worker-{int(shard_id)}.json"


def _lock_path(shard_id: int):
    return worker_stats_path(shard_id).with_suffix(".json.lock")


def _acquire_lock(shard_id: int, timeout: float = 3.0) -> int | None:
    path = _lock_path(shard_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 10.0:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.02)
    return None


def _release_lock(shard_id: int, fd: int | None) -> None:
    path = _lock_path(shard_id)
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_worker_file(shard_id: int) -> dict[str, Any]:
    path = worker_stats_path(shard_id)
    if not path.is_file():
        return {"v": _STORE_VER, "shard_id": int(shard_id), "bots": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"v": _STORE_VER, "shard_id": int(shard_id), "bots": {}}
    if not isinstance(raw, dict):
        return {"v": _STORE_VER, "shard_id": int(shard_id), "bots": {}}
    bots = raw.get("bots")
    if not isinstance(bots, dict):
        raw["bots"] = {}
    raw.setdefault("v", _STORE_VER)
    raw["shard_id"] = int(shard_id)
    return raw


def preserve_matcher_hist_from_file(shard_id: int, bots: dict[str, Any]) -> dict[str, Any]:
    """快速刷盘时保留磁盘上已有 matcher_hist，避免 3s 写入冲掉 30s 才更新的曲线。"""
    old_bots = _read_worker_file(shard_id).get("bots")
    if not isinstance(old_bots, dict):
        return bots
    merged: dict[str, Any] = {}
    for sid, rec in bots.items():
        row = dict(rec) if isinstance(rec, dict) else {}
        prev = old_bots.get(sid)
        if isinstance(prev, dict):
            hist = prev.get("matcher_hist")
            if isinstance(hist, list) and hist:
                row["matcher_hist"] = hist
        merged[str(sid)] = row
    return merged


def write_worker_stats_sync(
    *,
    shard_id: int,
    bots: dict[str, Any],
    preserve_matcher_hist: bool = False,
) -> None:
    """整文件覆写本 worker 快照（含各 QQ 的 by_plugin / matcher_duration_log / msg / 可选 matcher_hist）。"""
    payload = preserve_matcher_hist_from_file(shard_id, bots) if preserve_matcher_hist else bots
    fd = _acquire_lock(shard_id)
    if fd is None:
        return
    try:
        data: dict[str, Any] = {
            "v": _STORE_VER,
            "shard_id": int(shard_id),
            "updated_at": time.time(),
            "bots": payload,
        }
        path = worker_stats_path(shard_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        _release_lock(shard_id, fd)


def read_worker_stats(shard_id: int) -> dict[str, Any]:
    if not is_sharding_active():
        return {}
    data = _read_worker_file(shard_id)
    bots = data.get("bots")
    if not isinstance(bots, dict):
        return {}
    return {str(k): v for k, v in bots.items() if isinstance(v, dict)}


def iter_worker_shard_ids() -> list[int]:
    root = stats_dir()
    if not root.is_dir():
        return []
    out: list[int] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        m = _WORKER_FILE_RE.match(p.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def load_cluster_console_stats_by_sid() -> dict[str, dict[str, Any]]:
    """hub：合并各 worker stats 文件为 self_id -> bot 快照。"""
    if not is_sharding_active():
        return {}
    merged: dict[str, dict[str, Any]] = {}
    for sid_shard in iter_worker_shard_ids():
        for qq, rec in read_worker_stats(sid_shard).items():
            merged[str(qq)] = rec
    return merged


def load_worker_console_stats_for_boot(shard_id: int) -> dict[str, dict[str, Any]]:
    return read_worker_stats(shard_id)


def trim_worker_duration_logs_sync(*, shard_id: int, cap: int) -> None:
    """hub 定时清理：截断各 worker 文件内 matcher_duration_log（worker 进程不跑 WebUI 调度）。"""
    fd = _acquire_lock(shard_id)
    if fd is None:
        return
    try:
        data = _read_worker_file(shard_id)
        bots = data.get("bots")
        if not isinstance(bots, dict):
            return
        changed = False
        for rec in bots.values():
            if not isinstance(rec, dict):
                continue
            log = rec.get("matcher_duration_log")
            if isinstance(log, list) and len(log) > cap:
                rec["matcher_duration_log"] = log[-cap:]
                changed = True
        if changed:
            data["updated_at"] = time.time()
            path = worker_stats_path(shard_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
    finally:
        _release_lock(shard_id, fd)
