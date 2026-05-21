"""各 worker WS 连接状态写入共享文件，供 hub WebUI 展示全集群在线牛。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import get_shard_registry_settings, is_sharding_active

_PLUGIN = "pallas_shard"
_PRESENCE_FILE = "worker_presence.json"


def _presence_path():
    return plugin_data_dir(_PLUGIN, create=True) / _PRESENCE_FILE


def _lock_path():
    return _presence_path().with_suffix(".json.lock")


def _acquire_lock(timeout: float = 3.0) -> int | None:
    _presence_path().parent.mkdir(parents=True, exist_ok=True)
    path = _lock_path()
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


def _release_lock(fd: int | None) -> None:
    path = _lock_path()
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_data() -> dict[str, Any]:
    path = _presence_path()
    if not path.is_file():
        return {"bots": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"bots": {}}
    if not isinstance(raw, dict):
        return {"bots": {}}
    bots = raw.get("bots")
    if not isinstance(bots, dict):
        raw["bots"] = {}
    return raw


def _write_atomic(data: dict[str, Any]) -> None:
    path = _presence_path()
    data["updated_at"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mutate(fn) -> None:
    fd = _acquire_lock()
    if fd is None:
        return
    try:
        data = _read_data()
        fn(data)
        _write_atomic(data)
    finally:
        _release_lock(fd)


def note_worker_bot_connected_sync(
    *,
    qq: int,
    connection_key: str,
    adapter: str,
    shard_id: int,
    nickname: str = "",
) -> None:
    key = str(int(qq))
    nick = (nickname or "").strip()

    def upd(data: dict[str, Any]) -> None:
        bots = data.setdefault("bots", {})
        bots[key] = {
            "qq": int(qq),
            "shard_id": int(shard_id),
            "connection_key": connection_key,
            "adapter": adapter,
            "connected_at_unix": int(time.time()),
            "nickname": nick,
        }

    _mutate(upd)


def note_worker_bot_disconnected_sync(*, qq: int) -> None:
    key = str(int(qq))

    def upd(data: dict[str, Any]) -> None:
        bots = data.get("bots")
        if isinstance(bots, dict):
            bots.pop(key, None)

    _mutate(upd)


async def note_worker_bot_connected(bot) -> None:
    if not is_sharding_active():
        return
    try:
        qq = int(bot.self_id)
    except (TypeError, ValueError):
        return
    if not str(bot.self_id).isnumeric():
        return
    adapter = ""
    try:
        a = bot.adapter
        if a is not None and hasattr(a, "get_name"):
            adapter = str(a.get_name())
    except Exception:
        pass
    sid = get_shard_registry_settings().shard_id
    conn_key = str(getattr(bot, "self_id", qq))
    nickname = ""
    try:
        raw = await bot.call_api("get_login_info")
        if isinstance(raw, dict):
            nickname = str(raw.get("nickname") or "").strip()
    except Exception:
        pass
    await asyncio.to_thread(
        note_worker_bot_connected_sync,
        qq=qq,
        connection_key=conn_key,
        adapter=adapter,
        shard_id=sid,
        nickname=nickname,
    )


async def note_worker_bot_disconnected(qq: int) -> None:
    if not is_sharding_active():
        return
    await asyncio.to_thread(note_worker_bot_disconnected_sync, qq=int(qq))


def read_presence_bots() -> dict[str, dict[str, Any]]:
    if not is_sharding_active():
        return {}
    data = _read_data()
    bots = data.get("bots")
    if not isinstance(bots, dict):
        return {}
    return {str(k): v for k, v in bots.items() if isinstance(v, dict)}


def get_cluster_online_bot_ids() -> frozenset[int]:
    out: set[int] = set()
    for key, rec in read_presence_bots().items():
        try:
            out.add(int(rec.get("qq") or key))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def list_connected_bots_for_webui() -> list[dict[str, Any]]:
    """hub WebUI /bots：全 worker 已连接牛牛（不依赖 hub 进程 get_bots）。"""
    from src.common.webui.protocol_accounts import protocol_account_display_names

    names = protocol_account_display_names()
    rows: list[dict[str, Any]] = []
    for key in sorted(read_presence_bots().keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        rec = read_presence_bots()[key]
        qq = str(rec.get("qq") or key)
        nick = str(rec.get("nickname") or "").strip() or names.get(qq, "")
        rows.append({
            "connection_key": str(rec.get("connection_key") or qq),
            "self_id": qq,
            "adapter": str(rec.get("adapter") or ""),
            "connected_at_unix": rec.get("connected_at_unix"),
            "shard_id": rec.get("shard_id"),
            "nickname": nick,
            "online": True,
        })
    return rows


def pick_local_query_bot():
    """本 worker 任选一只有 API 能力的 Bot 用于查群成员。"""
    from nonebot import get_bots

    bots = get_bots()
    if not bots:
        return None
    return next(iter(bots.values()))


def bot_has_local_connection(qq: int) -> bool:
    from nonebot import get_bots

    return str(int(qq)) in get_bots()
