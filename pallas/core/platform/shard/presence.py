"""各 worker WS 连接状态：Redis HASH 或共享文件，供 hub WebUI 展示全集群在线牛。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.registry.config import get_shard_registry_settings

_PLUGIN = "pallas_shard"
_PRESENCE_FILE = "worker_presence.json"
_PRESENCE_STALE_SEC = 120.0
# 协议端 bot_offline 已上报但 WS 尚未断开时，reconcile 仍会从 get_bots 刷新 presence
_PROTOCOL_OFFLINE_QQS: set[int] = set()


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


def _mutate_file(fn) -> None:
    fd = _acquire_lock()
    if fd is None:
        return
    try:
        data = _read_data()
        if fn(data):
            _write_atomic(data)
    finally:
        _release_lock(fd)


def _read_file_bots() -> dict[str, dict[str, Any]]:
    data = _read_data()
    bots = data.get("bots")
    if not isinstance(bots, dict):
        return {}
    return {str(k): v for k, v in bots.items() if isinstance(v, dict)}


def _maybe_import_file_to_redis() -> None:
    from pallas.core.platform.coord.redis_presence import import_file_presence_to_redis_sync

    file_bots = _read_file_bots()
    if file_bots:
        import_file_presence_to_redis_sync(file_bots)


def _load_presence_bots() -> dict[str, dict[str, Any]]:
    from pallas.core.platform.coord.redis_presence import (
        presence_uses_redis_only,
        read_presence_bots_redis_sync,
    )

    file_bots = _read_file_bots()
    redis_bots = read_presence_bots_redis_sync()
    if redis_bots is not None:
        if not redis_bots:
            if file_bots:
                _maybe_import_file_to_redis()
                redis_bots = read_presence_bots_redis_sync()
        if redis_bots:
            return redis_bots
        # worker 仍写文件、hub 已读 Redis 时：Redis 空则回退文件，避免 WebUI 全离线
        if file_bots:
            return file_bots
        if presence_uses_redis_only():
            return {}
    return file_bots


def note_worker_bot_connected_sync(
    *,
    qq: int,
    connection_key: str,
    adapter: str,
    shard_id: int,
    nickname: str = "",
) -> None:
    from pallas.core.platform.coord.redis_presence import (
        note_worker_bot_connected_redis_sync,
        presence_uses_redis_only,
    )

    if note_worker_bot_connected_redis_sync(
        qq=qq,
        connection_key=connection_key,
        adapter=adapter,
        shard_id=shard_id,
        nickname=nickname,
    ):
        return
    if presence_uses_redis_only():
        return

    key = str(int(qq))
    nick = (nickname or "").strip()
    now = time.time()

    def upd(data: dict[str, Any]) -> None:
        bots = data.setdefault("bots", {})
        prev = bots.get(key)
        next_rec = {
            "qq": int(qq),
            "shard_id": int(shard_id),
            "connection_key": connection_key,
            "adapter": adapter,
            "connected_at_unix": int(now),
            "last_seen_at": now,
            "nickname": nick,
        }
        if (
            isinstance(prev, dict)
            and int(prev.get("qq") or 0) == int(qq)
            and int(prev.get("shard_id") or -1) == int(shard_id)
            and str(prev.get("connection_key") or "") == connection_key
            and str(prev.get("adapter") or "") == adapter
            and str(prev.get("nickname") or "") == nick
        ):
            prev["last_seen_at"] = now
            return True
        bots[key] = next_rec
        return True

    _mutate_file(upd)


def touch_worker_bot_presence_sync(*, qq: int) -> None:
    from pallas.core.platform.coord.redis_presence import (
        presence_uses_redis_only,
        touch_worker_bot_presence_redis_sync,
    )

    if touch_worker_bot_presence_redis_sync(qq=qq):
        return
    if presence_uses_redis_only():
        return

    key = str(int(qq))
    now = time.time()

    def upd(data: dict[str, Any]) -> bool:
        bots = data.get("bots")
        if not isinstance(bots, dict):
            return False
        rec = bots.get(key)
        if isinstance(rec, dict):
            rec["last_seen_at"] = now
            return True
        return False

    _mutate_file(upd)


def reconcile_local_worker_presence_sync(*, shard_id: int, local_qq_ids: set[int]) -> None:
    """对齐本 worker 实际连接：移除已断开记录，刷新在线牛的 last_seen，并补齐漏写的 presence。"""
    from pallas.core.platform.coord.redis_presence import (
        presence_uses_redis_only,
        reconcile_local_worker_presence_redis_sync,
    )

    if reconcile_local_worker_presence_redis_sync(shard_id=shard_id, local_qq_ids=local_qq_ids):
        return
    if presence_uses_redis_only():
        return

    now = time.time()
    sid = int(shard_id)

    def upd(data: dict[str, Any]) -> bool:
        bots = data.get("bots")
        changed = False
        if not isinstance(bots, dict):
            bots = {}
            data["bots"] = bots
        present_for_shard: set[int] = set()
        for key in list(bots.keys()):
            rec = bots.get(key)
            if not isinstance(rec, dict):
                bots.pop(key, None)
                changed = True
                continue
            if int(rec.get("shard_id") or -1) != sid:
                continue
            try:
                qq = int(rec.get("qq") or key)
            except (TypeError, ValueError):
                bots.pop(key, None)
                changed = True
                continue
            if qq not in local_qq_ids:
                bots.pop(key, None)
                changed = True
            else:
                present_for_shard.add(qq)
                rec["last_seen_at"] = now
        for qq in local_qq_ids:
            if qq in present_for_shard:
                continue
            key = str(int(qq))
            bots[key] = {
                "qq": int(qq),
                "shard_id": sid,
                "connection_key": key,
                "adapter": "",
                "connected_at_unix": int(now),
                "last_seen_at": now,
                "nickname": "",
            }
            changed = True
        return changed

    _mutate_file(upd)


def prune_stale_presence_entries_sync(*, max_age_sec: float = _PRESENCE_STALE_SEC) -> int:
    """移除长时间未刷新的 presence。"""
    from pallas.core.platform.coord.redis_presence import (
        presence_uses_redis_only,
        prune_stale_presence_entries_redis_sync,
    )

    removed = prune_stale_presence_entries_redis_sync(max_age_sec=max_age_sec)
    if removed is not None:
        return removed
    if presence_uses_redis_only():
        return 0

    now = time.time()
    file_removed = 0

    def upd(data: dict[str, Any]) -> bool:
        nonlocal file_removed
        bots = data.get("bots")
        if not isinstance(bots, dict):
            return False
        changed = False
        for key in list(bots.keys()):
            rec = bots.get(key)
            if not isinstance(rec, dict):
                bots.pop(key, None)
                file_removed += 1
                changed = True
                continue
            last = float(rec.get("last_seen_at") or rec.get("connected_at_unix") or 0)
            if last <= 0 or now - last > max_age_sec:
                bots.pop(key, None)
                file_removed += 1
                changed = True
        return changed

    _mutate_file(upd)
    return file_removed


def mark_protocol_bot_offline_sync(*, qq: int) -> None:
    """NapCat/Lagrange 离线通知：立刻清集群 presence，并在 WS 僵尸期间跳过 reconcile。"""
    _PROTOCOL_OFFLINE_QQS.add(int(qq))
    note_worker_bot_disconnected_sync(qq=int(qq))


def clear_protocol_bot_offline_sync(*, qq: int) -> None:
    _PROTOCOL_OFFLINE_QQS.discard(int(qq))


def filter_local_qq_ids_for_presence(local_qq_ids: set[int]) -> set[int]:
    from pallas.core.platform.shard.presence_health import health_quarantine_qq_ids

    blocked = set(_PROTOCOL_OFFLINE_QQS) | set(health_quarantine_qq_ids())
    if not blocked:
        return local_qq_ids
    return {qq for qq in local_qq_ids if qq not in blocked}


async def mark_protocol_bot_offline(qq: int) -> None:
    await asyncio.to_thread(mark_protocol_bot_offline_sync, qq=int(qq))


async def clear_protocol_bot_offline(qq: int) -> None:
    await asyncio.to_thread(clear_protocol_bot_offline_sync, qq=int(qq))


async def close_local_bot_connection(qq: int) -> bool:
    """主动关闭本进程 WS，触发 on_bot_disconnect。"""
    from nonebot import get_bots

    key = str(int(qq))
    bot = get_bots().get(key)
    if bot is None:
        return False
    try:
        adapter = getattr(bot, "adapter", None)
        connections = getattr(adapter, "connections", None)
        if not isinstance(connections, dict):
            return False
        websocket = connections.get(key)
        if websocket is None:
            return False
        await websocket.close(4000, "protocol offline")
        return True
    except Exception:
        return False


def note_worker_bot_disconnected_sync(*, qq: int) -> None:
    from pallas.core.platform.coord.redis_presence import (
        note_worker_bot_disconnected_redis_sync,
        presence_uses_redis_only,
    )

    if note_worker_bot_disconnected_redis_sync(qq=qq):
        return
    if presence_uses_redis_only():
        return

    key = str(int(qq))

    def upd(data: dict[str, Any]) -> bool:
        bots = data.get("bots")
        if isinstance(bots, dict):
            if key in bots:
                bots.pop(key, None)
                return True
        return False

    _mutate_file(upd)


async def note_worker_bot_connected(bot) -> None:
    if not shard_ctx.sharding_active():
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
    await asyncio.to_thread(
        note_worker_bot_connected_sync,
        qq=qq,
        connection_key=conn_key,
        adapter=adapter,
        shard_id=sid,
        nickname="",
    )


async def note_worker_bot_disconnected(qq: int) -> None:
    if not shard_ctx.sharding_active():
        return
    await asyncio.to_thread(note_worker_bot_disconnected_sync, qq=int(qq))


def read_presence_bots() -> dict[str, dict[str, Any]]:
    if not shard_ctx.sharding_active():
        return {}
    prune_stale_presence_entries_sync()
    return _load_presence_bots()


def get_cluster_online_bot_ids() -> frozenset[int]:
    out: set[int] = set()
    for key, rec in read_presence_bots().items():
        try:
            out.add(int(rec.get("qq") or key))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def count_connected_bots_for_reporting() -> int:
    """与控制台 /bots、社区统计心跳的 online_bots 口径一致。"""
    from pallas.core.platform.bot_runtime.roles import is_sharded_hub

    if shard_ctx.sharding_active() and is_sharded_hub():
        return len(get_cluster_online_bot_ids())
    from nonebot import get_bots

    return len(get_bots())


def list_connected_bots_for_webui() -> list[dict[str, Any]]:
    """hub WebUI /bots：全 worker 已连接牛牛。"""
    from pallas.console.webui.protocol_accounts import protocol_account_display_names

    names = protocol_account_display_names()
    bots = read_presence_bots()
    rows: list[dict[str, Any]] = []
    for key in sorted(bots.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        rec = bots[key]
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
    """本 worker 用最小 QQ 的 Bot 查群成员。"""
    from nonebot import get_bots

    from pallas.core.platform.shard.local_representative import local_worker_representative_bot_id

    rep = local_worker_representative_bot_id()
    bots = get_bots()
    if rep is not None and str(rep) in bots:
        return bots[str(rep)]
    if not bots:
        return None
    return next(iter(bots.values()))


def bot_has_local_connection(qq: int) -> bool:
    from nonebot import get_bots

    return str(int(qq)) in get_bots()


def bot_has_cluster_connection(qq: int) -> bool:
    """本 worker 已连接，或分片下 presence 记录里任意 worker 已连接。"""
    bid = int(qq)
    if bot_has_local_connection(bid):
        return True
    if not shard_ctx.sharding_active():
        return False
    return bid in get_cluster_online_bot_ids()
