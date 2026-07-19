import asyncio
import time
from collections.abc import Iterable

from nonebot import logger

from pallas.core.foundation.config import GroupConfig, UserConfig
from pallas.product.ban_gate.snapshot import (
    fallback_db_timeout_sec,
    is_group_banned_fast,
    is_user_blocked_in_group_fast,
    is_user_globally_banned_fast,
    patch_group_banned,
    patch_group_blocked_users,
    patch_user_banned,
    schedule_ban_gate_snapshot_refresh,
)

_IS_BANNED_DB_TIMEOUT_SEC = fallback_db_timeout_sec()
_BAN_GATE_CACHE_TTL_SEC = 45.0
_BAN_GATE_CACHE_MAX = 50_000
_ban_gate_cache: dict[int, tuple[float, bool]] = {}
_ban_gate_lock = asyncio.Lock()
# invalidate 时递增；门禁写回缓存前比对，避免与进行中的查询交叉污染
_user_gate_generation: dict[int, int] = {}
_user_fetch_tasks: dict[int, asyncio.Task[bool]] = {}
_user_fetch_tasks_lock = asyncio.Lock()

_GROUP_BAN_GATE_CACHE_TTL_SEC = 45.0
_group_ban_gate_cache: dict[int, tuple[float, frozenset[int]]] = {}
_group_ban_gate_lock = asyncio.Lock()
_group_gate_generation: dict[int, int] = {}
_group_fetch_tasks: dict[int, asyncio.Task[frozenset[int]]] = {}
_group_fetch_tasks_lock = asyncio.Lock()

_GROUP_SELF_BAN_GATE_CACHE_TTL_SEC = 45.0
_group_self_banned_cache: dict[int, tuple[float, bool]] = {}
_group_self_ban_gate_lock = asyncio.Lock()
_group_self_gate_generation: dict[int, int] = {}
_group_self_fetch_tasks: dict[int, asyncio.Task[bool]] = {}
_group_self_fetch_tasks_lock = asyncio.Lock()


async def apply_user_banned_change(user_id: int, banned: bool) -> None:
    """WebUI / 命令写入 user_config.banned 后同步 ACL 行、本进程快照与门禁。"""
    await patch_user_banned(user_id, banned)
    await _sync_acl_user_banned(user_id, banned)
    await invalidate_user_ban_gate_cache(user_id)


async def apply_group_banned_change(group_id: int, banned: bool) -> None:
    await patch_group_banned(group_id, banned)
    await _sync_acl_group_banned(group_id, banned)
    await invalidate_group_ban_gate_cache(group_id)


async def apply_group_blocked_users_change(group_id: int, user_ids: list[int]) -> None:
    await patch_group_blocked_users(group_id, user_ids)
    await _sync_acl_group_blocked_users(group_id, user_ids)
    await invalidate_group_ban_gate_cache(group_id)


async def _sync_acl_user_banned(user_id: int, banned: bool) -> None:
    try:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
    except Exception:
        return
    role = "用户"
    subj = f"u:{int(user_id)}"
    try:
        if banned:
            await repo.upsert_rule(
                role=role,
                subject=subj,
                action="event.receive",
                target_scope="全局",
                target="*",
                effect="deny",
                priority=2000,
                source="system",
            )
        else:
            await repo.delete_by_signature(
                role=role,
                subject=subj,
                action="event.receive",
                target_scope="全局",
                target="*",
            )
    except Exception:
        from nonebot import logger

        logger.exception("ban_gate: failed to mirror user ban into ACL uid={}", user_id)


async def _sync_acl_group_banned(group_id: int, banned: bool) -> None:
    try:
        from pallas.core.foundation.db import make_acl_repository
        from pallas.core.perm.acl import ACL_TARGET_GROUP_BAN

        repo = make_acl_repository()
    except Exception:
        return
    role = "群"
    subj = f"g:{int(group_id)}"
    try:
        if banned:
            await repo.upsert_rule(
                role=role,
                subject=subj,
                action="event.receive",
                target_scope="全局",
                target=ACL_TARGET_GROUP_BAN,
                effect="deny",
                priority=2000,
                source="system",
            )
        else:
            await repo.delete_by_signature(
                role=role,
                subject=subj,
                action="event.receive",
                target_scope="全局",
                target=ACL_TARGET_GROUP_BAN,
            )
    except Exception:
        from nonebot import logger

        logger.exception("ban_gate: failed to mirror group ban into ACL gid={}", group_id)


async def _sync_acl_group_blocked_users(group_id: int, user_ids: list[int]) -> None:
    """将 GroupConfig.blocked_user_ids 与 ACL 表 reconcile：
    当前列表里的人在 ACL 中以 deny 形式存在；
    不在列表里的历史 deny 行同步删除。
    """
    try:
        from pallas.core.foundation.db import make_acl_repository
        from pallas.core.perm.acl import group_block_target

        repo = make_acl_repository()
    except Exception:
        return
    target_prefix = group_block_target(group_id)
    new_uids = {int(u) for u in user_ids}
    try:
        # 1) upsert 当前 uid 集合（命中即 priority=1000 deny）
        for uid in new_uids:
            await repo.upsert_rule(
                role="用户",
                subject=f"u:{uid}",
                action="event.receive",
                target_scope="全局",
                target=target_prefix,
                effect="deny",
                priority=1000,
                source="system",
            )
        # 2) 列出该 group 全部历史 ACL 行，剔除仍存在于 new_uids 的，差集删除
        all_rules = await repo.list_matching_rules(action="event.receive", target=target_prefix)
        stale_uids: set[int] = set()
        for r in all_rules:
            if r.role != "用户":
                continue
            subj = getattr(r, "subject", "") or ""
            if not subj.startswith("u:"):
                continue
            try:
                rid = int(subj[2:])
            except ValueError:
                continue
            if rid not in new_uids:
                stale_uids.add(rid)
        for rid in stale_uids:
            await repo.delete_by_signature(
                role="用户",
                subject=f"u:{rid}",
                action="event.receive",
                target_scope="全局",
                target=target_prefix,
            )
    except Exception:
        from nonebot import logger

        logger.exception("ban_gate: failed to mirror group blocked users into ACL gid={}", group_id)


async def invalidate_user_ban_gate_cache(uids: int | Iterable[int]) -> None:
    """使给定 QQ 的门禁缓存失效。"""
    ids = [uids] if isinstance(uids, int) else list(uids)
    if not ids:
        return
    async with _ban_gate_lock:
        for u in ids:
            _ban_gate_cache.pop(u, None)
            _user_gate_generation[u] = _user_gate_generation.get(u, 0) + 1
    schedule_ban_gate_snapshot_refresh()


async def reset_user_ban_gate_cache() -> None:
    """清空全局门禁内存缓存。"""
    async with _user_fetch_tasks_lock:
        for t in list(_user_fetch_tasks.values()):
            if not t.done():
                t.cancel()
        _user_fetch_tasks.clear()
    async with _ban_gate_lock:
        _ban_gate_cache.clear()
        _user_gate_generation.clear()


async def invalidate_group_ban_gate_cache(group_ids: int | Iterable[int] | None = None) -> None:
    """使给定群的「本群拉黑 / 群封禁」门禁缓存失效；不传参则清空全部。"""
    if group_ids is None:
        async with _group_fetch_tasks_lock:
            for t in list(_group_fetch_tasks.values()):
                if not t.done():
                    t.cancel()
            _group_fetch_tasks.clear()
        async with _group_self_fetch_tasks_lock:
            for t in list(_group_self_fetch_tasks.values()):
                if not t.done():
                    t.cancel()
            _group_self_fetch_tasks.clear()
        async with _group_ban_gate_lock:
            _group_ban_gate_cache.clear()
            _group_gate_generation.clear()
        async with _group_self_ban_gate_lock:
            _group_self_banned_cache.clear()
            _group_self_gate_generation.clear()
        return
    async with _group_ban_gate_lock:
        ids = [group_ids] if isinstance(group_ids, int) else list(group_ids)
        for g in ids:
            gid = int(g)
            _group_ban_gate_cache.pop(gid, None)
            _group_gate_generation[gid] = _group_gate_generation.get(gid, 0) + 1
    async with _group_self_ban_gate_lock:
        for g in ids:
            gid = int(g)
            _group_self_banned_cache.pop(gid, None)
            _group_self_gate_generation[gid] = _group_self_gate_generation.get(gid, 0) + 1
    schedule_ban_gate_snapshot_refresh()


async def reset_group_ban_gate_cache() -> None:
    """清空本群拉黑门禁内存缓存。"""
    await invalidate_group_ban_gate_cache(None)


async def _fetch_user_banned_db(user_id: int) -> bool:
    try:
        return await asyncio.wait_for(
            UserConfig(user_id).is_banned(),
            timeout=_IS_BANNED_DB_TIMEOUT_SEC,
        )
    except TimeoutError:
        logger.warning("user ban gate: is_banned timeout uid={}", user_id)
        return False
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("user ban gate: is_banned failed uid={}", user_id)
        return False


async def _await_user_ban_deduped(user_id: int) -> bool:
    """同一 uid 并发只打一次库，减轻大群刷屏时连接池与 DB 压力。"""
    async with _user_fetch_tasks_lock:
        t = _user_fetch_tasks.get(user_id)
        if t is not None and not t.done():
            task = t
        else:

            async def _runner() -> bool:
                try:
                    return await _fetch_user_banned_db(user_id)
                finally:
                    async with _user_fetch_tasks_lock:
                        cur = asyncio.current_task()
                        if _user_fetch_tasks.get(user_id) is cur:
                            _user_fetch_tasks.pop(user_id, None)

            task = asyncio.create_task(_runner())
            _user_fetch_tasks[user_id] = task
    return await asyncio.shield(task)


async def query_user_ban_status_for_gate(user_id: int) -> bool:
    """
    查询用户是否全局拉黑。
    数据库超时或异常时返回 False，避免连接堆积或事件链卡死。
    """
    fast = is_user_globally_banned_fast(user_id)
    if fast is not None:
        return fast

    while True:
        now = time.monotonic()
        async with _ban_gate_lock:
            hit = _ban_gate_cache.get(user_id)
            if hit is not None:
                exp, val = hit
                if now < exp:
                    return val
                del _ban_gate_cache[user_id]
            if len(_ban_gate_cache) > _BAN_GATE_CACHE_MAX:
                stale = [k for k, (e, _) in _ban_gate_cache.items() if now >= e]
                for k in stale:
                    del _ban_gate_cache[k]
                if len(_ban_gate_cache) > _BAN_GATE_CACHE_MAX:
                    _ban_gate_cache.clear()
            gen_snapshot = _user_gate_generation.get(user_id, 0)

        banned = await _await_user_ban_deduped(user_id)

        expire_at = time.monotonic() + _BAN_GATE_CACHE_TTL_SEC
        async with _ban_gate_lock:
            if _user_gate_generation.get(user_id, 0) != gen_snapshot:
                continue
            _ban_gate_cache[user_id] = (expire_at, banned)
        return banned


async def _fetch_group_blocked_ids_db(group_id: int) -> frozenset[int]:
    try:
        ids_list = await asyncio.wait_for(
            GroupConfig(group_id).blocked_user_ids(),
            timeout=_IS_BANNED_DB_TIMEOUT_SEC,
        )
        return frozenset(ids_list)
    except TimeoutError:
        logger.warning("group ban gate: blocked_user_ids timeout gid={}", group_id)
        return frozenset()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("group ban gate: blocked_user_ids failed gid={}", group_id)
        return frozenset()


async def _await_group_blocked_deduped(group_id: int) -> frozenset[int]:
    async with _group_fetch_tasks_lock:
        t = _group_fetch_tasks.get(group_id)
        if t is not None and not t.done():
            task = t
        else:

            async def _runner() -> frozenset[int]:
                try:
                    return await _fetch_group_blocked_ids_db(group_id)
                finally:
                    async with _group_fetch_tasks_lock:
                        cur = asyncio.current_task()
                        if _group_fetch_tasks.get(group_id) is cur:
                            _group_fetch_tasks.pop(group_id, None)

            task = asyncio.create_task(_runner())
            _group_fetch_tasks[group_id] = task
    return await asyncio.shield(task)


async def query_group_blocked_for_gate(group_id: int, user_id: int) -> bool:
    """本群拉黑名单；超时/异常 fail-open。"""
    fast = is_user_blocked_in_group_fast(group_id, user_id)
    if fast is not None:
        return fast

    while True:
        now = time.monotonic()
        async with _group_ban_gate_lock:
            hit = _group_ban_gate_cache.get(group_id)
            if hit is not None:
                exp, uids = hit
                if now < exp:
                    return user_id in uids
                del _group_ban_gate_cache[group_id]
            if len(_group_ban_gate_cache) > _BAN_GATE_CACHE_MAX:
                stale = [k for k, (e, _) in _group_ban_gate_cache.items() if now >= e]
                for k in stale:
                    del _group_ban_gate_cache[k]
                if len(_group_ban_gate_cache) > _BAN_GATE_CACHE_MAX:
                    _group_ban_gate_cache.clear()
            gen_snapshot = _group_gate_generation.get(group_id, 0)

        fs = await _await_group_blocked_deduped(group_id)
        blocked = user_id in fs
        expire_at = time.monotonic() + _GROUP_BAN_GATE_CACHE_TTL_SEC
        async with _group_ban_gate_lock:
            if _group_gate_generation.get(group_id, 0) != gen_snapshot:
                continue
            _group_ban_gate_cache[group_id] = (expire_at, fs)
        return blocked


async def _fetch_group_banned_db(group_id: int) -> bool:
    try:
        return await asyncio.wait_for(
            GroupConfig(group_id).is_banned(),
            timeout=_IS_BANNED_DB_TIMEOUT_SEC,
        )
    except TimeoutError:
        logger.warning("group self ban gate: is_banned timeout gid={}", group_id)
        return False
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("group self ban gate: is_banned failed gid={}", group_id)
        return False


async def _await_group_banned_deduped(group_id: int) -> bool:
    async with _group_self_fetch_tasks_lock:
        t = _group_self_fetch_tasks.get(group_id)
        if t is not None and not t.done():
            task = t
        else:

            async def _runner() -> bool:
                try:
                    return await _fetch_group_banned_db(group_id)
                finally:
                    async with _group_self_fetch_tasks_lock:
                        cur = asyncio.current_task()
                        if _group_self_fetch_tasks.get(group_id) is cur:
                            _group_self_fetch_tasks.pop(group_id, None)

            task = asyncio.create_task(_runner())
            _group_self_fetch_tasks[group_id] = task
    return await asyncio.shield(task)


async def query_group_ban_status_for_gate(group_id: int) -> bool:
    """群是否被全局拉黑；超时/异常 fail-open。"""
    fast = is_group_banned_fast(group_id)
    if fast is not None:
        return fast

    while True:
        now = time.monotonic()
        async with _group_self_ban_gate_lock:
            hit = _group_self_banned_cache.get(group_id)
            if hit is not None:
                exp, val = hit
                if now < exp:
                    return val
                del _group_self_banned_cache[group_id]
            if len(_group_self_banned_cache) > _BAN_GATE_CACHE_MAX:
                stale = [k for k, (e, _) in _group_self_banned_cache.items() if now >= e]
                for k in stale:
                    del _group_self_banned_cache[k]
                if len(_group_self_banned_cache) > _BAN_GATE_CACHE_MAX:
                    _group_self_banned_cache.clear()
            gen_snapshot = _group_self_gate_generation.get(group_id, 0)

        banned = await _await_group_banned_deduped(group_id)

        expire_at = time.monotonic() + _GROUP_SELF_BAN_GATE_CACHE_TTL_SEC
        async with _group_self_ban_gate_lock:
            if _group_self_gate_generation.get(group_id, 0) != gen_snapshot:
                continue
            _group_self_banned_cache[group_id] = (expire_at, banned)
        return banned
