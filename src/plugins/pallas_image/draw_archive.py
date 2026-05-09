from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path

from nonebot import logger

from src.common.paths import plugin_data_dir

_ARCHIVE_SUBDIR = "draw_archive"
_INDEX_NAME = "index.json"
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_RETENTION_SEC = 30 * 86400
_lock = asyncio.Lock()


def archive_dir() -> Path:
    return plugin_data_dir("pallas_image") / _ARCHIVE_SUBDIR


def index_path() -> Path:
    return archive_dir() / _INDEX_NAME


def _load_index_sync() -> list[dict]:
    p = index_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("draw_archive 索引无法解析，将重建: {}", e)
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path_s = item.get("path")
        if not isinstance(path_s, str):
            continue
        try:
            sz = int(item.get("size", 0))
            ts = int(item.get("ts", 0))
        except (TypeError, ValueError):
            continue
        out.append({"path": path_s, "size": max(0, sz), "ts": ts})
    return out


def _save_index_sync(entries: list[dict]) -> None:
    index_path().parent.mkdir(parents=True, exist_ok=True)
    index_path().write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _cleanup_index_sync(entries: list[dict]) -> list[dict]:
    now = int(time.time())
    cutoff = now - _RETENTION_SEC
    alive: list[dict] = []
    for e in entries:
        fp = Path(e["path"])
        if not fp.is_file():
            continue
        if int(e["ts"]) < cutoff:
            try:
                fp.unlink(missing_ok=True)
            except OSError as ex:
                logger.debug("draw_archive 删除过期文件失败: {} {}", fp, ex)
            continue
        alive.append(e)

    total = sum(int(x["size"]) for x in alive)
    alive.sort(key=lambda x: int(x["ts"]))
    while total > _MAX_TOTAL_BYTES and alive:
        first = alive.pop(0)
        fp = Path(first["path"])
        try:
            fp.unlink(missing_ok=True)
        except OSError as ex:
            logger.debug("draw_archive 删文件失败: {} {}", fp, ex)
        total -= int(first.get("size", 0))
    return alive


def _persist_sync(data: bytes, group_id: int, user_id: int) -> None:
    d = archive_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}_{group_id}_{user_id}.png"
    fp = d / name
    fp.write_bytes(data)
    entries = _load_index_sync()
    entries.append({"path": str(fp.resolve()), "size": len(data), "ts": int(time.time())})
    entries = _cleanup_index_sync(entries)
    _save_index_sync(entries)


async def persist_generated_draw(data: bytes, group_id: int, user_id: int) -> None:
    if not data:
        return
    async with _lock:

        def _run():
            try:
                _persist_sync(data, group_id, user_id)
            except Exception as e:
                logger.warning("draw_archive 写入失败: {}", e)

        await asyncio.to_thread(_run)


async def random_archived_png_bytes() -> bytes | None:
    async with _lock:

        def _pick() -> bytes | None:
            entries = _load_index_sync()
            candidates = [e for e in entries if Path(e["path"]).is_file()]
            if not candidates:
                return None
            choice = random.choice(candidates)
            try:
                return Path(choice["path"]).read_bytes()
            except OSError as e:
                logger.debug("draw_archive 读取失败: {}", e)
                return None

        return await asyncio.to_thread(_pick)
