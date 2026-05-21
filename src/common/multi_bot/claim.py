"""多 Bot / 多进程：同一条群消息仅一只牛抢占处理权。"""

from __future__ import annotations

import asyncio
import os
import time

from src.common.paths import plugin_data_dir

_CLAIM_MAX_AGE_SEC = 86400


def _claim_path(plugin: str, group_id: int, message_id: int):
    root = plugin_data_dir(plugin) / "message_claims"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{group_id}_{message_id}.claim"


def _prune_old_claims(plugin: str, *, max_files: int = 500) -> None:
    root = plugin_data_dir(plugin) / "message_claims"
    if not root.is_dir():
        return
    files = sorted(root.glob("*.claim"), key=lambda p: p.stat().st_mtime, reverse=True)
    now = time.time()
    for p in files[max_files:]:
        try:
            if now - p.stat().st_mtime > _CLAIM_MAX_AGE_SEC:
                p.unlink(missing_ok=True)
        except OSError:
            pass


def try_claim_message_sync(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
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
        _prune_old_claims(plugin)
        return True
    except FileExistsError:
        try:
            return int(path.read_text(encoding="utf-8").strip()) == bot_id
        except (ValueError, OSError):
            return False


async def try_claim_message(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
    return await asyncio.to_thread(try_claim_message_sync, plugin, group_id, message_id, bot_id)
