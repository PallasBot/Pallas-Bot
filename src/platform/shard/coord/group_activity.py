"""跨 worker 同群独占活动的通用 Redis 互斥。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from src.platform.shard.coord.coord_redis_store import (
    coord_key,
    mutate_json_sync,
    read_json_sync,
    setex_json_sync,
)
from src.platform.shard.registry.config import (
    get_shard_registry_settings,
    is_sharding_active,
)

ActivityGate = Literal["ok", "busy"]

LiveSessionCheck = Callable[[dict[str, Any]], bool]


def session_live_by_until(data: dict[str, Any]) -> bool:
    return float(data.get("session_until") or 0) > time.time()


def session_live_by_pair(data: dict[str, Any]) -> bool:
    pair = data.get("session_pair")
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return False
    return session_live_by_until(data)


def session_live_by_flag(data: dict[str, Any], *, flag_key: str = "session_active") -> bool:
    if not data.get(flag_key):
        return False
    return session_live_by_until(data)


@dataclass
class GroupActivityLock:
    """同群同时仅允许一场插件活动；分片时经 Redis 跨 worker 互斥。"""

    namespace: str
    busy_ttl_sec: float = 7200.0
    orphan_min_age_sec: float = 30.0
    session_extra_keys: frozenset[str] = frozenset()
    is_live_session: LiveSessionCheck = session_live_by_until
    local_busy: set[int] = field(default_factory=set)

    def key(self, group_id: int) -> str:
        return coord_key(self.namespace, group_id)

    def read(self, group_id: int) -> dict[str, Any] | None:
        return read_json_sync(self.key(group_id))

    def store(self, group_id: int, data: dict[str, Any]) -> None:
        setex_json_sync(self.key(group_id), data, self._ttl(data))

    def _ttl(self, data: dict[str, Any]) -> int:
        until = float(data.get("until") or 0)
        if until > time.time():
            return max(60, int(until - time.time()) + 60)
        return int(self.busy_ttl_sec)

    def _mutate(self, group_id: int, fn, *, retries: int = 8) -> dict[str, Any] | None:
        return mutate_json_sync(
            self.key(group_id),
            fn,
            ttl_sec_fn=self._ttl,
            retries=retries,
        )

    def is_orphan_lock(self, data: dict[str, Any] | None) -> bool:
        if not data or not data.get("busy"):
            return False
        acquired = float(data.get("acquired_at") or 0)
        if acquired <= 0 or time.time() < acquired + self.orphan_min_age_sec:
            return False
        return not self.is_live_session(data)

    def mark_session(self, group_id: int, **fields: Any) -> None:
        if not is_sharding_active():
            return
        now = time.time()

        def stamp(data: dict[str, Any]) -> None:
            data["session_until"] = now + self.busy_ttl_sec
            if fields:
                data.update(fields)

        self._mutate(int(group_id), stamp)

    def clear_session(self, group_id: int) -> None:
        if not is_sharding_active():
            return

        def stamp(data: dict[str, Any]) -> None:
            data.pop("session_until", None)
            for key in self.session_extra_keys:
                data.pop(key, None)

        self._mutate(int(group_id), stamp)

    def try_begin(self, group_id: int) -> bool:
        gid = int(group_id)
        if not is_sharding_active():
            if gid in self.local_busy:
                return False
            self.local_busy.add(gid)
            return True

        now = time.time()
        sid = get_shard_registry_settings().shard_id
        acquired = False

        def claim(data: dict[str, Any]) -> None:
            nonlocal acquired
            until = float(data.get("until") or 0)
            if until > now and data.get("busy"):
                acquired = False
                return
            payload: dict[str, Any] = {
                "group_id": gid,
                "busy": True,
                "until": now + self.busy_ttl_sec,
                "shard_id": int(sid),
                "acquired_at": now,
            }
            for key in self.session_extra_keys:
                payload.setdefault(key, False if key.endswith("_active") else None)
            data.update(payload)
            acquired = True

        self._mutate(gid, claim)
        return acquired

    def end(self, group_id: int) -> None:
        gid = int(group_id)
        if not is_sharding_active():
            self.local_busy.discard(gid)
            return

        def release(data: dict[str, Any]) -> None:
            data["busy"] = False
            data["until"] = 0
            data.pop("session_until", None)
            for key in self.session_extra_keys:
                data.pop(key, None)

        self._mutate(gid, release)

    async def try_reclaim_orphan(
        self,
        group_id: int,
        *,
        has_local: bool = False,
        local_alive: Callable[[], Any] | None = None,
    ) -> bool:
        gid = int(group_id)
        if not is_sharding_active():
            if gid not in self.local_busy:
                return False
            if has_local:
                return False
            if local_alive is not None:
                result = local_alive()
                if hasattr(result, "__await__"):
                    result = await result
                if result:
                    return False
            self.local_busy.discard(gid)
            return True

        if has_local:
            return False
        data = self.read(gid)
        if not self.is_orphan_lock(data):
            return False
        self.end(gid)
        return True

    async def begin(
        self,
        group_id: int,
        *,
        has_local: bool = False,
        local_alive: Callable[[], Any] | None = None,
    ) -> ActivityGate:
        gid = int(group_id)
        if self.try_begin(gid):
            return "ok"
        if not (
            await self.try_reclaim_orphan(gid, has_local=has_local, local_alive=local_alive) and self.try_begin(gid)
        ):
            return "busy"
        return "ok"


_lock_cache: dict[str, GroupActivityLock] = {}


def get_group_activity_lock(
    namespace: str,
    *,
    busy_ttl_sec: float = 7200.0,
    orphan_min_age_sec: float = 30.0,
    session_extra_keys: frozenset[str] | None = None,
    is_live_session: LiveSessionCheck | None = None,
) -> GroupActivityLock:
    if namespace not in _lock_cache:
        _lock_cache[namespace] = GroupActivityLock(
            namespace=namespace,
            busy_ttl_sec=busy_ttl_sec,
            orphan_min_age_sec=orphan_min_age_sec,
            session_extra_keys=session_extra_keys or frozenset(),
            is_live_session=is_live_session or session_live_by_until,
        )
    return _lock_cache[namespace]


async def begin_group_activity(
    lock: GroupActivityLock,
    group_id: int,
    *,
    has_local: bool = False,
    local_alive: Callable[[], Any] | None = None,
) -> ActivityGate:
    return await lock.begin(group_id, has_local=has_local, local_alive=local_alive)
