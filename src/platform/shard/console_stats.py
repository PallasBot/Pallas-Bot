"""分片 worker 控制台指标落盘；hub 读取合并。"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from operator import itemgetter
from pathlib import Path
from typing import Any

from src.foundation.paths import plugin_data_dir
from src.platform.shard.registry.config import is_sharding_active

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


def process_memory_snapshot() -> dict[str, int]:
    try:
        import psutil  # type: ignore

        mem = psutil.Process().memory_info()
        return {"rss": int(mem.rss), "vms": int(mem.vms)}
    except Exception:  # noqa: BLE001
        pass
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        parts = Path("/proc/self/statm").read_text(encoding="utf-8").strip().split()
        if len(parts) >= 2:
            return {"rss": int(parts[1]) * page_size, "vms": int(parts[0]) * page_size}
    except Exception:  # noqa: BLE001
        pass
    return {}


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
    worker_meta: dict[str, Any] | None = None,
) -> None:
    """整文件覆写本 worker 快照。"""
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
        if worker_meta:
            data.update(worker_meta)
        path = worker_stats_path(shard_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        _release_lock(shard_id, fd)


def read_worker_stats_file(shard_id: int) -> dict[str, Any]:
    return _read_worker_file(shard_id)


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


def bot_authoritative_shard_map() -> dict[str, int]:
    """牛牛归属分片：在线 presence 优先，否则注册表 assignments。"""
    out: dict[str, int] = {}
    try:
        from src.platform.shard.presence import read_presence_bots

        for qq, rec in read_presence_bots().items():
            key = str(qq).strip()
            if not key or not isinstance(rec, dict):
                continue
            try:
                out[key] = int(rec.get("shard_id"))
            except (TypeError, ValueError):
                continue
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.platform.shard.registry.store import get_shard_registry

        reg = get_shard_registry()
        for qq, shard_id in reg.assignments.items():
            key = str(qq).strip()
            if key and key not in out:
                out[key] = int(shard_id)
    except Exception:  # noqa: BLE001
        pass
    return out


def load_cluster_console_stats_by_sid() -> dict[str, dict[str, Any]]:
    """hub：按牛牛归属分片合并 worker stats，避免迁分片后旧 worker 快照覆盖/拼进总日志。"""
    if not is_sharding_active():
        return {}
    auth = bot_authoritative_shard_map()
    by_qq: dict[str, list[tuple[int, dict[str, Any], float]]] = defaultdict(list)
    for sid_shard in iter_worker_shard_ids():
        data = _read_worker_file(sid_shard)
        try:
            updated = float(data.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated = 0.0
        for qq, rec in read_worker_stats(sid_shard).items():
            key = str(qq).strip()
            if key and isinstance(rec, dict):
                by_qq[key].append((sid_shard, rec, updated))
    merged: dict[str, dict[str, Any]] = {}
    for qq, entries in by_qq.items():
        target = auth.get(qq)
        if target is not None:
            matched = [e for e in entries if e[0] == target]
            if matched:
                entries = matched
        best = max(entries, key=itemgetter(2))
        merged[qq] = best[1]
    return merged


def prune_stale_worker_stats_bots_sync() -> int:
    """hub：从各 worker 文件移除注册表已迁走的牛牛快照。"""
    try:
        from src.platform.shard.registry.store import get_shard_registry

        reg = get_shard_registry()
    except Exception:  # noqa: BLE001
        return 0
    removed = 0
    for sid_shard in iter_worker_shard_ids():
        allowed = {str(k).strip() for k in reg.bots_on_shard(sid_shard) if str(k).strip()}
        fd = _acquire_lock(sid_shard)
        if fd is None:
            continue
        try:
            data = _read_worker_file(sid_shard)
            bots = data.get("bots")
            if not isinstance(bots, dict) or not bots:
                continue
            kept: dict[str, Any] = {}
            for qq, rec in bots.items():
                key = str(qq).strip()
                if key and key in allowed:
                    kept[key] = rec
            if len(kept) == len(bots):
                continue
            removed += len(bots) - len(kept)
            data["bots"] = kept
            data["updated_at"] = time.time()
            path = worker_stats_path(sid_shard)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        finally:
            _release_lock(sid_shard, fd)
    return removed


def load_worker_console_stats_for_boot(shard_id: int) -> dict[str, dict[str, Any]]:
    return read_worker_stats(shard_id)


def trim_worker_duration_logs_sync(*, shard_id: int, cap: int) -> None:
    """hub 定时清理：截断各 worker 文件内 matcher_duration_log。"""
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
            if isinstance(log, list) and log:
                from src.plugins.pallas_webui.extended_api import enforce_matcher_duration_log_limits

                trimmed = log[-cap:]
                enforce_matcher_duration_log_limits(trimmed)
                if trimmed != log:
                    rec["matcher_duration_log"] = trimmed
                    changed = True
        if changed:
            data["updated_at"] = time.time()
            path = worker_stats_path(shard_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
    finally:
        _release_lock(shard_id, fd)
