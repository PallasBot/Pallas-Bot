from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING

import pytest

from pallas.core.platform.federate import peer_bots as mod

if TYPE_CHECKING:
    from collections.abc import Iterator


class BlockingRosterRedis:
    def __init__(self, *, block_scan: bool = True) -> None:
        self.block_scan = block_scan
        self.scan_started = threading.Event()
        self.second_scan_started = threading.Event()
        self.release_scan = threading.Event()
        self.main_thread_id = threading.get_ident()
        self.main_thread_zrem = threading.Event()
        self.loop_heartbeat = threading.Event()
        self.loop_advanced_during_zrem: bool | None = None
        self.remote_groups: list[bytes] = []
        self.active_scans = 0
        self.peak_scans = 0
        self.scan_calls = 0
        self.published_payloads: list[dict[str, object]] = []
        self._lock = threading.Lock()

    def scan_iter(self, **_kwargs: object) -> Iterator[bytes]:
        with self._lock:
            self.active_scans += 1
            self.scan_calls += 1
            self.peak_scans = max(self.peak_scans, self.active_scans)
            if self.scan_calls >= 2:
                self.second_scan_started.set()
        self.scan_started.set()
        try:
            if self.block_scan:
                self.release_scan.wait(5)
            return iter([b"pallas:fed:pool:peer_bots:peer"])
        finally:
            with self._lock:
                self.active_scans -= 1

    def get(self, _key: object) -> str:
        return json.dumps({
            "deployment_id": "peer",
            "bot_ids": [2],
            "present_group_ids": [7],
        })

    def zremrangebyscore(self, *_args: object) -> int:
        if threading.get_ident() == self.main_thread_id:
            self.main_thread_zrem.set()
            self.loop_advanced_during_zrem = self.loop_heartbeat.wait(0.1)
        return 0

    def zrangebyscore(self, *_args: object) -> list[bytes]:
        return self.remote_groups

    def set(self, _key: object, value: str, **_kwargs: object) -> bool:
        self.published_payloads.append(json.loads(value))
        return True

    def pipeline(self) -> FakePipeline:
        return FakePipeline()


class FakePipeline:
    def zadd(self, *_args: object) -> FakePipeline:
        return self

    def zremrangebyscore(self, *_args: object) -> FakePipeline:
        return self

    def expire(self, *_args: object) -> FakePipeline:
        return self

    def execute(self) -> list[object]:
        return []


class BlockingTouchRedis:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.loop_heartbeat = threading.Event()
        self.loop_advanced_during_execute: bool | None = None
        self.batches: list[dict[str, float]] = []
        self.cleanup_ranges: list[tuple[object, ...]] = []
        self.expiries: list[int] = []
        self._lock = threading.Lock()

    def pipeline(self) -> TouchPipeline:
        return TouchPipeline(self)

    def execute(self, values: dict[str, float]) -> list[object]:
        with self._lock:
            self.batches.append(values)
            first = len(self.batches) == 1
        if first:
            self.started.set()
            self.loop_advanced_during_execute = self.loop_heartbeat.wait(2)
            self.release.wait(5)
        return []


class TouchPipeline:
    def __init__(self, redis: BlockingTouchRedis) -> None:
        self.redis = redis
        self.values: dict[str, float] = {}

    def zadd(self, _key: object, values: dict[str, float]) -> TouchPipeline:
        self.values.update(values)
        return self

    def zremrangebyscore(self, *args: object) -> TouchPipeline:
        self.redis.cleanup_ranges.append(args)
        return self

    def expire(self, _key: object, seconds: int) -> TouchPipeline:
        self.redis.expiries.append(seconds)
        return self

    def execute(self) -> list[object]:
        return self.redis.execute(self.values)


class FailOnceTouchRedis:
    def __init__(self) -> None:
        self.calls = 0

    def pipeline(self) -> FailOnceTouchPipeline:
        return FailOnceTouchPipeline(self)


class FailOnceTouchPipeline:
    def __init__(self, redis: FailOnceTouchRedis) -> None:
        self.redis = redis

    def zadd(self, *_args: object) -> FailOnceTouchPipeline:
        return self

    def zremrangebyscore(self, *_args: object) -> FailOnceTouchPipeline:
        return self

    def expire(self, *_args: object) -> FailOnceTouchPipeline:
        return self

    def execute(self) -> list[object]:
        self.redis.calls += 1
        if self.redis.calls == 1:
            raise OSError("simulated Redis failure")
        return []


def prepare_roster_sync(monkeypatch: pytest.MonkeyPatch, redis: BlockingRosterRedis) -> None:
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_ingress_enabled", lambda: True)
    monkeypatch.setattr(mod, "resolved_federate_id", lambda: "local")
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: redis)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "local")
    monkeypatch.setattr(mod, "get_catalog_bot_ids", lambda: frozenset({1}))
    monkeypatch.setattr(mod, "collect_local_federate_online_bot_ids", lambda: frozenset({1}))
    monkeypatch.setattr(mod, "collect_local_federate_command_capabilities", lambda: frozenset())
    monkeypatch.setattr(mod, "collect_local_command_permission_levels", dict)
    monkeypatch.setattr(mod, "local_federate_deployment_name", lambda: "local")
    monkeypatch.setattr(mod, "get_local_group_admin_bot_ids", lambda _group_id: None)

    async def build_roster(*, resolve_login_nicknames: bool = True) -> mod.FederatePeerBotRoster:
        _ = resolve_login_nicknames
        return mod.FederatePeerBotRoster(
            deployment_id="local",
            deployment_name="local",
            bot_ids=frozenset({1}),
            online_bot_ids=frozenset({1}),
            public_bot_ids=frozenset(),
        )

    monkeypatch.setattr(mod, "_build_local_federate_bot_roster", build_roster)


@pytest.mark.asyncio
async def test_roster_refresh_coalesces_concurrent_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)

    callers = [asyncio.create_task(mod.sync_federate_peer_bot_roster()) for _ in range(6)]
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)
    await asyncio.sleep(0.05)
    redis.release_scan.set()
    await asyncio.gather(*callers)

    assert redis.peak_scans == 1
    assert redis.scan_calls == 1


@pytest.mark.asyncio
async def test_roster_refresh_follows_connect_and_disconnect_during_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.multi_bot import connected_roster

    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)
    monkeypatch.setattr(connected_roster, "_connected_bots", {10})
    monkeypatch.setattr(mod, "get_catalog_bot_ids", lambda: frozenset(connected_roster.connected_bot_ids()))

    async def build_roster(*, resolve_login_nicknames: bool = True) -> mod.FederatePeerBotRoster:
        _ = resolve_login_nicknames
        bot_ids = frozenset(connected_roster.connected_bot_ids())
        return mod.FederatePeerBotRoster("local", "local", bot_ids, bot_ids, frozenset())

    monkeypatch.setattr(mod, "_build_local_federate_bot_roster", build_roster)
    first = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)

    connected_roster.note_connected_bot(20)
    connect = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    connected_roster.note_disconnected_bot(10)
    disconnect = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    redis.release_scan.set()
    await asyncio.gather(first, connect, disconnect)

    assert redis.scan_calls == 2
    assert redis.peak_scans == 1
    assert redis.published_payloads[-1]["bot_ids"] == [20]


@pytest.mark.asyncio
async def test_cancelled_roster_waiter_does_not_abandon_shared_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)
    cancelled_waiter = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)
    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter

    shared_task = mod._roster_sync_task
    assert shared_task is not None
    assert not shared_task.done()
    next_waiter = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    redis.release_scan.set()
    await next_waiter

    assert redis.peak_scans == 1
    assert redis.scan_calls == 2


@pytest.mark.asyncio
async def test_cancelled_roster_owner_joins_scan_before_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)
    waiter = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)
    owner = mod._roster_sync_task
    assert owner is not None
    owner.cancel()
    followup = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    await asyncio.sleep(0.05)

    assert not owner.done()
    assert redis.scan_calls == 1
    assert redis.peak_scans == 1

    redis.release_scan.set()
    await asyncio.gather(waiter, followup)
    assert redis.scan_calls == 2
    assert redis.peak_scans == 1


@pytest.mark.asyncio
async def test_roster_failure_keeps_last_cache_and_later_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis(block_scan=False)
    prepare_roster_sync(monkeypatch, redis)
    client = [None]
    active = [False]
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client[0])
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: active[0])
    mod._cache_ids = frozenset({99})

    await mod.sync_federate_peer_bot_roster()
    assert mod.get_federate_peer_bot_ids() == frozenset({99})

    client[0] = redis
    active[0] = True
    await mod.sync_federate_peer_bot_roster()
    assert mod.get_federate_peer_bot_ids() == frozenset({2})


@pytest.mark.asyncio
async def test_reset_ignores_inflight_roster_cache_result(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)
    mod._cache_ids = frozenset({99})
    syncing = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)
    stale_trigger = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    await asyncio.sleep(0)

    mod.clear_federate_peer_bot_cache_for_tests()
    redis.release_scan.set()
    await asyncio.gather(syncing, stale_trigger)

    assert mod.get_federate_peer_bot_ids() == frozenset()
    assert redis.scan_calls == 1


@pytest.mark.asyncio
async def test_stop_joins_roster_io_before_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)
    mod.start_federate_peer_bot_sync_loop()
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)

    stopping = asyncio.create_task(mod.stop_federate_peer_bot_sync_loop())
    await asyncio.sleep(0)
    assert not stopping.done()
    await asyncio.gather(
        mod.sync_federate_peer_bot_roster(),
        mod.sync_federate_peer_bot_roster(),
    )
    mod.touch_federate_present_group(77)
    assert mod._local_present_groups[77] > 0
    assert mod._roster_sync_requested is False
    assert mod._present_touch_task is None
    redis.release_scan.set()
    await stopping
    assert mod._roster_sync_task is None
    assert mod._sync_task is None

    mod.start_federate_peer_bot_sync_loop()
    assert await asyncio.wait_for(asyncio.to_thread(redis.second_scan_started.wait, 5), timeout=6)
    assert mod._sync_task is not None
    assert redis.peak_scans == 1
    assert redis.scan_calls == 2
    await mod.stop_federate_peer_bot_sync_loop()
    assert 77 in redis.published_payloads[-1]["present_group_ids"]


@pytest.mark.asyncio
async def test_stop_prevents_queued_roster_task_from_starting_io(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis()
    prepare_roster_sync(monkeypatch, redis)
    request = asyncio.create_task(mod.sync_federate_peer_bot_roster())
    stopping = asyncio.create_task(mod.stop_federate_peer_bot_sync_loop())
    await asyncio.gather(request, stopping)

    assert redis.scan_calls == 0
    assert mod._roster_sync_task is None

    mod.start_federate_peer_bot_sync_loop()
    assert await asyncio.wait_for(asyncio.to_thread(redis.scan_started.wait, 5), timeout=6)
    redis.release_scan.set()
    await mod.stop_federate_peer_bot_sync_loop()
    assert redis.scan_calls == 1


@pytest.mark.asyncio
async def test_roster_sync_never_reads_present_groups_on_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = BlockingRosterRedis(block_scan=False)
    prepare_roster_sync(monkeypatch, redis)
    mod._local_present_groups[7] = time.time()
    loop = asyncio.get_running_loop()
    stop_pulse = threading.Event()

    def schedule_heartbeat() -> None:
        while not stop_pulse.is_set():
            if redis.main_thread_zrem.wait(0.01):
                loop.call_soon_threadsafe(redis.loop_heartbeat.set)
                return

    pulse = threading.Thread(target=schedule_heartbeat, daemon=True)
    pulse.start()
    await mod.sync_federate_peer_bot_roster()
    stop_pulse.set()
    await asyncio.to_thread(pulse.join, 1)

    assert not redis.main_thread_zrem.is_set()
    assert redis.loop_advanced_during_zrem is None


@pytest.mark.asyncio
async def test_local_present_groups_still_merge_shared_zset(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = BlockingRosterRedis(block_scan=False)
    redis.remote_groups = [b"2"]
    prepare_roster_sync(monkeypatch, redis)

    groups = await asyncio.to_thread(mod.collect_local_present_group_ids, ((1, time.time()),))

    assert groups == [1, 2]


@pytest.mark.asyncio
async def test_present_group_touch_is_local_first_and_coalesces_remote_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod.clear_federate_peer_bot_cache_for_tests()
    redis = BlockingTouchRedis()
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: redis)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "local")
    monkeypatch.setattr(mod, "_PRESENT_GROUP_REMOTE_TOUCH_INTERVAL_SEC", 0.01)
    monkeypatch.setattr(mod, "_PRESENT_GROUP_PUBLISH_CAP", 3)
    loop = asyncio.get_running_loop()

    def pulse_after_write_starts() -> None:
        if redis.started.wait(5):
            loop.call_soon_threadsafe(redis.loop_heartbeat.set)
            redis.loop_heartbeat.wait(2)
            redis.release.set()

    pulse = threading.Thread(target=pulse_after_write_starts, daemon=True)
    pulse.start()
    mod.touch_federate_present_group(1)
    first_local_touch = mod._local_present_groups[1]
    assert await asyncio.wait_for(asyncio.to_thread(redis.started.wait, 5), timeout=6)
    assert mod._local_present_groups[1] == first_local_touch
    assert await asyncio.wait_for(asyncio.to_thread(redis.loop_heartbeat.wait, 2), timeout=3)

    await asyncio.sleep(0.02)
    mod.touch_federate_present_group(1)
    latest_local_touch = mod._local_present_groups[1]
    mod.touch_federate_present_group(2)
    mod.touch_federate_present_group(3)
    redis.release.set()
    await mod.stop_federate_peer_bot_sync_loop()
    await asyncio.to_thread(pulse.join, 2)

    assert redis.loop_advanced_during_execute is True
    assert len(redis.batches) == 2
    assert len(redis.cleanup_ranges) == 2
    expected_key = mod.federate_present_groups_redis_key("local")
    assert all(args[0] == expected_key for args in redis.cleanup_ranges)
    assert all(args[1] == "-inf" for args in redis.cleanup_ranges)
    expected_expiry = int(mod._PRESENT_GROUP_WINDOW_SEC) + int(mod._PUBLISH_TTL_SEC)
    assert redis.expiries == [expected_expiry] * 2
    assert redis.batches[0] == {"1": first_local_touch}
    assert redis.batches[1] == {
        "1": latest_local_touch,
        "2": mod._local_present_groups[2],
        "3": mod._local_present_groups[3],
    }
    assert mod._present_touch_task is None


@pytest.mark.asyncio
async def test_present_group_touch_failure_keeps_throttle_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod.clear_federate_peer_bot_cache_for_tests()
    redis = FailOnceTouchRedis()
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: redis)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "local")
    monkeypatch.setattr(mod, "_PRESENT_GROUP_REMOTE_TOUCH_INTERVAL_SEC", 0.02)

    mod.touch_federate_present_group(5)
    first_writer = mod._present_touch_task
    assert first_writer is not None
    await first_writer
    mod.touch_federate_present_group(5)
    assert redis.calls == 1

    await asyncio.sleep(0.03)
    mod.touch_federate_present_group(5)
    second_writer = mod._present_touch_task
    assert second_writer is not None
    await second_writer
    assert redis.calls == 2


@pytest.mark.asyncio
async def test_pending_present_touches_discard_expired_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    mod.clear_federate_peer_bot_cache_for_tests()
    redis = BlockingTouchRedis()
    redis.loop_heartbeat.set()
    now = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: now[0])
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: redis)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "local")
    try:
        mod.touch_federate_present_group(1)
        assert await asyncio.wait_for(asyncio.to_thread(redis.started.wait, 5), timeout=6)
        mod.touch_federate_present_group(2)
        now[0] += mod._PRESENT_GROUP_WINDOW_SEC + 1
        mod.touch_federate_present_group(3)

        assert set(mod._local_present_groups) == {3}
        assert set(mod._pending_present_group_touches) == {3}
    finally:
        redis.release.set()
        await mod.stop_federate_peer_bot_sync_loop()

    assert len(redis.batches) == 2
    assert redis.batches[1] == {"3": now[0]}
    assert all("2" not in batch for batch in redis.batches)


@pytest.mark.asyncio
async def test_pending_present_touches_are_bounded_and_keep_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    mod.clear_federate_peer_bot_cache_for_tests()
    redis = BlockingTouchRedis()
    redis.loop_heartbeat.set()
    now = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: now[0])
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: redis)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "local")
    monkeypatch.setattr(mod, "_PRESENT_GROUP_PUBLISH_CAP", 2)
    try:
        mod.touch_federate_present_group(1)
        assert await asyncio.wait_for(asyncio.to_thread(redis.started.wait, 5), timeout=6)
        for group_id in (2, 3, 4):
            now[0] += 1
            mod.touch_federate_present_group(group_id)
            assert len(mod._pending_present_group_touches) <= 2

        assert set(mod._local_present_groups) == {1, 2, 3, 4}
        assert mod._pending_present_group_touches == {3: 1002.0, 4: 1003.0}
    finally:
        redis.release.set()
        await mod.stop_federate_peer_bot_sync_loop()


@pytest.mark.asyncio
async def test_cancelled_present_writer_does_not_overlap_its_redis_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    mod.clear_federate_peer_bot_cache_for_tests()
    redis = BlockingTouchRedis()
    redis.loop_heartbeat.set()
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: redis)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "local")
    try:
        mod.touch_federate_present_group(1)
        assert await asyncio.wait_for(asyncio.to_thread(redis.started.wait, 5), timeout=6)
        writer = mod._present_touch_task
        assert writer is not None
        writer.cancel()
        await asyncio.wait({writer}, timeout=0.05)
        mod.touch_federate_present_group(2)
        for _ in range(10):
            await asyncio.sleep(0.01)

        assert len(redis.batches) == 1
    finally:
        redis.release.set()
        await mod.stop_federate_peer_bot_sync_loop()
