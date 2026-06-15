"""多 Bot 同群：协议可能对同一条群消息向每个连接各上报一次，用内容签名去重/抢占。"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import defaultdict, deque

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from src.platform.multi_bot.claim import read_claim_owner_sync, try_claim_message
from src.platform.shard import context as shard_ctx

_GROUP_EVENT_DEDUP_MAX = 4000
_group_event_dedup_lock = asyncio.Lock()
_group_event_sigs: deque[tuple[int, int, str, int]] = deque()
_group_event_sig_set: set[tuple[int, int, str, int]] = set()

_CROSS_BOT_CLAIM_MAX = 4000
_cross_bot_claim_lock = asyncio.Lock()
CrossBotSig = tuple[int, int, str] | tuple[int, int, str, int]
_cross_bot_claim_owners: dict[tuple[str, CrossBotSig], int] = {}

_GROUP_MESSAGE_ONCE_MAX = 4000
_group_message_once_keys: set[tuple[str, CrossBotSig]] = set()
_group_message_once_order: deque[tuple[str, CrossBotSig]] = deque()


def needs_persistent_message_claim() -> bool:
    """分片等多进程场景才写 Redis/文件 claim；单进程仅用内存。"""
    return shard_ctx.sharding_active()


def needs_group_host_bot_gate() -> bool:
    """分片或同进程多牛时才需主持牛 owned gate；单牛单进程不启用。"""
    from nonebot import get_bots

    if shard_ctx.sharding_active():
        return True
    return len(get_bots()) > 1


def normalize_group_raw_message(raw_message: str) -> str:
    # 与 ChatData / learn 侧一致，避免图片子类型差异导致去重失败
    return re.sub(r"\.image,.+?\]", ".image]", raw_message)


def normalize_group_plaintext(plaintext: str) -> str:
    return re.sub(r"\s+", " ", plaintext.strip())


def normalize_message_time(message_time: int) -> int:
    t = int(message_time)
    if t > 10_000_000_000:
        return t // 1000
    return t


def cross_bot_message_signature(
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> CrossBotSig:
    """多牛抢占签名：默认群+用户+正文；决斗/八角笼可含 message_time 区分场次。"""
    body = normalize_group_plaintext(message_body) if use_plaintext else normalize_group_raw_message(message_body)
    if include_message_time:
        return (group_id, user_id, body, normalize_message_time(message_time))
    return (group_id, user_id, body)


def cross_bot_group_message_key(
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> int:
    """各 Bot 连接的 message_id 不同；同一条物理消息用此键做文件抢占。"""
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    if len(sig) == 4:
        payload = f"{sig[0]}:{sig[1]}:{sig[2]}:{sig[3]}"
    else:
        payload = f"{sig[0]}:{sig[1]}:{sig[2]}"
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:15], 16)


def _prune_cross_bot_claims() -> None:
    if len(_cross_bot_claim_owners) <= _CROSS_BOT_CLAIM_MAX:
        return
    for key in list(_cross_bot_claim_owners.keys())[: _CROSS_BOT_CLAIM_MAX // 2]:
        _cross_bot_claim_owners.pop(key, None)


def _prune_group_message_once_keys() -> None:
    while len(_group_message_once_order) >= _GROUP_MESSAGE_ONCE_MAX:
        old = _group_message_once_order.popleft()
        _group_message_once_keys.discard(old)


async def try_claim_cross_bot_message_memory(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    bot_id: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    key = (plugin, sig)
    async with _cross_bot_claim_lock:
        owner = _cross_bot_claim_owners.get(key)
        if owner is None:
            _cross_bot_claim_owners[key] = bot_id
            _prune_cross_bot_claims()
            return True
        return owner == bot_id


async def try_claim_cross_bot_message(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    bot_id: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    """同进程内存抢占；分片等多进程时再走 Redis/文件 claim。"""
    if not await try_claim_cross_bot_message_memory(
        plugin,
        group_id,
        user_id,
        message_body,
        message_time,
        bot_id,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    ):
        return False
    if not needs_persistent_message_claim():
        return True
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    return await try_claim_message(plugin, group_id, claim_key, bot_id)


async def try_claim_group_message_once(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    """同条群消息只处理一次：重复连接、同牛二次进 matcher 均不再通过。"""
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    key = (plugin, sig)
    async with _cross_bot_claim_lock:
        if key in _group_message_once_keys:
            return False
        _group_message_once_keys.add(key)
        _group_message_once_order.append(key)
        _prune_group_message_once_keys()
    if not needs_persistent_message_claim():
        return True
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    if await try_claim_message(plugin, group_id, claim_key, 0):
        return True
    async with _cross_bot_claim_lock:
        _group_message_once_keys.discard(key)
    return False


def ingress_shard_claim_owner_obsolete(owner: int) -> bool:
    """registry 中已不存在的分片 id 视为过期 claim owner。"""
    from src.platform.shard.registry import get_shard_registry

    reg = get_shard_registry()
    known = {int(s.id) for s in reg.shards}
    return int(owner) not in known


async def try_claim_cross_shard_message_memory(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    shard_id: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    key = (plugin, sig)
    async with _cross_bot_claim_lock:
        owner = _cross_bot_claim_owners.get(key)
        if owner is None:
            _cross_bot_claim_owners[key] = shard_id
            _prune_cross_bot_claims()
            return True
        if owner == shard_id:
            return True
        if ingress_shard_claim_owner_obsolete(owner):
            _cross_bot_claim_owners[key] = shard_id
            return True
        return False


_shard_ingress_file_locks: dict[tuple[str, tuple[int, int, str]], asyncio.Lock] = defaultdict(asyncio.Lock)


async def try_claim_cross_shard_message(
    plugin: str,
    group_id: int,
    user_id: int,
    message_body: str,
    message_time: int,
    shard_id: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
    bot_id: int | None = None,
) -> bool:
    """分片 ingress：全舰队每条消息仅一个 shard 通过；该 shard 上各牛不再互斥。"""
    if not await try_claim_cross_shard_message_memory(
        plugin,
        group_id,
        user_id,
        message_body,
        message_time,
        shard_id,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    ):
        return False
    sig = cross_bot_message_signature(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        message_body,
        message_time,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )
    lock_key = (plugin, sig)
    async with _shard_ingress_file_locks[lock_key]:
        owner = await asyncio.to_thread(read_claim_owner_sync, plugin, group_id, claim_key)
        if owner is not None:
            if owner == shard_id:
                return True
            if ingress_shard_claim_owner_obsolete(owner):
                from src.platform.multi_bot.claim import take_claim_message

                return await take_claim_message(plugin, group_id, claim_key, shard_id)
            return False
        if bot_id is not None:
            from src.platform.shard.local_representative import is_local_worker_representative

            if not is_local_worker_representative(bot_id):
                for _ in range(20):
                    owner = await asyncio.to_thread(read_claim_owner_sync, plugin, group_id, claim_key)
                    if owner is not None:
                        if owner == shard_id:
                            return True
                        if ingress_shard_claim_owner_obsolete(owner):
                            from src.platform.multi_bot.claim import take_claim_message

                            return await take_claim_message(plugin, group_id, claim_key, shard_id)
                        return False
                    await asyncio.sleep(0.01)
                return False
        return await try_claim_message(plugin, group_id, claim_key, shard_id)


async def should_skip_duplicate_group_event(
    group_id: int,
    user_id: int,
    norm_raw: str,
    message_time: int,
) -> bool:
    sig = (group_id, user_id, norm_raw, normalize_message_time(message_time))
    async with _group_event_dedup_lock:
        if sig in _group_event_sig_set:
            return True
        while len(_group_event_sigs) >= _GROUP_EVENT_DEDUP_MAX:
            old = _group_event_sigs.popleft()
            _group_event_sig_set.discard(old)
        _group_event_sigs.append(sig)
        _group_event_sig_set.add(sig)
        return False


_GROUP_GATE_LOCK = asyncio.Lock()
_owned_gate: dict[tuple[str, int], tuple[int, float]] = {}
_broadcast_slot_until: dict[tuple[str, int], float] = {}


async def try_begin_group_owned_gate(
    plugin: str,
    group_id: int,
    bot_id: int,
    *,
    gate_sec: float,
) -> bool:
    """同群短时占位：窗口内仅已占位 bot 可再次通过，其它 bot 拒绝。"""

    if shard_ctx.sharding_active():
        from src.platform.shard.coord.group_gate import try_begin_owned_gate_sync

        return await asyncio.to_thread(
            try_begin_owned_gate_sync,
            plugin,
            group_id,
            bot_id,
            gate_sec=gate_sec,
        )
    ttl = max(1.0, float(gate_sec))
    now = time.time()
    key = (plugin, group_id)
    async with _GROUP_GATE_LOCK:
        rec = _owned_gate.get(key)
        if rec is not None:
            owner, until = rec
            if now < until:
                return owner == bot_id
        _owned_gate[key] = (bot_id, now + ttl)
        if len(_owned_gate) > 2000:
            expired = [k for k, (_, u) in _owned_gate.items() if u <= now]
            for k in expired:
                _owned_gate.pop(k, None)
        return True


async def try_acquire_group_broadcast_slot(
    plugin: str,
    group_id: int,
    *,
    ttl_sec: float = 3.0,
) -> bool:
    """同群短时广播占位：窗口内仅首次调用返回 True。"""

    if shard_ctx.sharding_active():
        from src.platform.shard.coord.group_gate import try_acquire_broadcast_slot_sync

        return await asyncio.to_thread(
            try_acquire_broadcast_slot_sync,
            plugin,
            group_id,
            ttl_sec=ttl_sec,
        )
    ttl = max(0.1, float(ttl_sec))
    now = time.time()
    key = (plugin, group_id)
    async with _GROUP_GATE_LOCK:
        until = _broadcast_slot_until.get(key, 0.0)
        if now < until:
            return False
        _broadcast_slot_until[key] = now + ttl
        if len(_broadcast_slot_until) > 2000:
            expired = [k for k, u in _broadcast_slot_until.items() if u <= now]
            for k in expired:
                _broadcast_slot_until.pop(k, None)
        return True


async def bind_group_owned_gate(
    plugin: str,
    group_id: int,
    bot_id: int,
    *,
    gate_sec: float,
) -> None:
    await asyncio.to_thread(bind_group_owned_gate_sync, plugin, group_id, bot_id, gate_sec=gate_sec)


def bind_group_owned_gate_sync(plugin: str, group_id: int, bot_id: int, *, gate_sec: float) -> None:
    """强制绑定同群主持牛。"""

    if shard_ctx.sharding_active():
        from src.platform.shard.coord.group_gate import bind_owned_gate_sync

        bind_owned_gate_sync(plugin, int(group_id), int(bot_id), gate_sec=gate_sec)
    ttl = max(1.0, float(gate_sec))
    _owned_gate[(plugin, int(group_id))] = (int(bot_id), time.time() + ttl)


async def is_group_owned_gate_holder(plugin: str, group_id: int, bot_id: int) -> bool:

    if shard_ctx.sharding_active():
        from src.platform.shard.coord.group_gate import is_owned_gate_holder_sync

        return await asyncio.to_thread(
            is_owned_gate_holder_sync,
            plugin,
            int(group_id),
            int(bot_id),
        )
    now = time.time()
    rec = _owned_gate.get((plugin, int(group_id)))
    if rec is None:
        return True
    owner, until = rec
    if now >= until:
        return True
    return owner == int(bot_id)


def release_group_owned_gate_sync(plugin: str, group_id: int) -> None:
    """释放同群主持牛占位。"""

    if shard_ctx.sharding_active():
        from src.platform.shard.coord.group_gate import release_owned_gate_sync

        release_owned_gate_sync(plugin, int(group_id))
    _owned_gate.pop((plugin, int(group_id)), None)


async def release_group_owned_gate(plugin: str, group_id: int) -> None:
    await asyncio.to_thread(release_group_owned_gate_sync, plugin, int(group_id))


async def try_begin_group_draw_cheer(group_id: int, bot_id: int, *, gate_sec: float) -> bool:
    """兼容：等同 try_begin_group_owned_gate(\"draw\", ...)。"""
    return await try_begin_group_owned_gate("draw", group_id, bot_id, gate_sec=gate_sec)


async def begin_group_exclusive_activity(
    namespace: str,
    group_id: int,
    *,
    has_local: bool = False,
    local_alive=None,
) -> str:
    """分片下同群独占活动开闸；namespace 即 Redis 协调键前缀。"""
    from src.platform.shard.coord.group_activity import begin_group_activity, get_group_activity_lock

    lock = get_group_activity_lock(namespace)
    return await begin_group_activity(
        lock,
        group_id,
        has_local=has_local,
        local_alive=local_alive,
    )


async def claim_group_message_event(
    plugin: str,
    group_event: GroupMessageEvent,
    bot_id: int,
    *,
    use_plaintext: bool = True,
    include_message_time: bool = False,
) -> bool:
    """本 Bot 是否应处理该条群消息。未抢占返回 False。"""
    return await try_claim_cross_bot_message(
        plugin,
        group_event.group_id,
        group_event.user_id,
        group_event.get_plaintext(),
        group_event.time,
        bot_id,
        use_plaintext=use_plaintext,
        include_message_time=include_message_time,
    )


async def claim_group_handler(
    plugin: str,
    event: MessageEvent,
    bot_id: int,
    *,
    use_plaintext: bool = True,
) -> bool:
    """群消息走 claim_group_message_event；私聊恒为 True。"""
    if not isinstance(event, GroupMessageEvent):
        return True
    return await claim_group_message_event(plugin, event, bot_id, use_plaintext=use_plaintext)
