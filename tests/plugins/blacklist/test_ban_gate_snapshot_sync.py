from __future__ import annotations

import asyncio
import time
from threading import Event, Thread, get_ident
from unittest.mock import AsyncMock

import pytest

from pallas.product.ban_gate import snapshot


@pytest.fixture(autouse=True)
async def reset_snapshot():
    await snapshot.reset_ban_gate_snapshot_for_tests()
    snapshot._synced_redis_gen = -1
    snapshot._remote_gen_checked_at = 0.0
    yield
    await snapshot.reset_ban_gate_snapshot_for_tests()


def test_sync_remote_generation_detects_bump(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.gen = 1

        def get(self, _key):
            return str(self.gen).encode()

        def incr(self, _key):
            self.gen += 1
            return self.gen

    fake = FakeRedis()
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    snapshot._synced_redis_gen = 0
    snapshot._remote_gen_checked_at = 0.0

    assert snapshot.sync_ban_gate_snapshot_remote_generation() is True
    assert snapshot.sync_ban_gate_snapshot_remote_generation() is False

    fake.gen = 2
    snapshot._remote_gen_checked_at = 0.0
    assert snapshot.sync_ban_gate_snapshot_remote_generation() is True


def test_sync_remote_generation_ttl_and_redis_failure(monkeypatch):
    class FakeRedis:
        calls = 0

        def get(self, _key):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("redis unavailable")
            return b"4"

    fake = FakeRedis()
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    snapshot._synced_redis_gen = 3
    snapshot._remote_gen_checked_at = 0.0

    assert snapshot.sync_ban_gate_snapshot_remote_generation() is True
    assert snapshot.sync_ban_gate_snapshot_remote_generation() is False
    assert fake.calls == 1

    snapshot._remote_gen_checked_at = 0.0
    assert snapshot.sync_ban_gate_snapshot_remote_generation() is False
    assert snapshot._synced_redis_gen == 4
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_async_remote_generation_ttl_failure_and_missing_redis(monkeypatch):
    class FakeRedis:
        calls = 0
        fail = False

        def get(self, _key):
            self.calls += 1
            if self.fail:
                raise RuntimeError("redis unavailable")
            return b"4"

    fake = FakeRedis()
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    snapshot._synced_redis_gen = 3
    snapshot._remote_gen_checked_at = 0.0

    assert await snapshot._sync_ban_gate_snapshot_remote_generation() is True
    assert await snapshot._sync_ban_gate_snapshot_remote_generation() is False
    assert fake.calls == 1
    snapshot._ready = True
    snapshot._global_banned = frozenset({881_005})

    snapshot._remote_gen_checked_at = 0.0
    fake.fail = True
    assert await snapshot._sync_ban_gate_snapshot_remote_generation() is False
    assert snapshot._synced_redis_gen == 4
    assert fake.calls == 2
    assert snapshot.is_user_globally_banned_fast(881_005) is True

    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: None,
    )
    snapshot._remote_gen_checked_at = 0.0
    assert await snapshot._sync_ban_gate_snapshot_remote_generation() is False
    assert snapshot._synced_redis_gen == 4
    assert snapshot.is_user_globally_banned_fast(881_005) is True


@pytest.mark.asyncio
async def test_local_ban_patch_precedes_nonblocking_remote_bump(monkeypatch):
    from packages.blacklist import apply_user_banned_change

    class FakeRedis:
        started = Event()
        release = Event()
        thread_id = None

        def incr(self, _key):
            self.thread_id = get_ident()
            self.started.set()
            self.release.wait()
            return 1

    fake = FakeRedis()
    visible = Event()
    remote_bump_released_after_patch = Event()
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    monkeypatch.setattr(snapshot, "refresh_ban_gate_snapshot", AsyncMock())
    monkeypatch.setattr("packages.blacklist.ban_gate._sync_acl_user_banned", AsyncMock())

    def release_guard() -> None:
        fake.started.wait(5)
        if visible.wait(2):
            remote_bump_released_after_patch.set()
        fake.release.set()

    guard = Thread(target=release_guard, daemon=True)
    guard.start()
    uid = 881_004
    mark_snapshot_ready()
    await apply_user_banned_change(uid, True)
    assert snapshot.is_user_globally_banned_fast(uid) is True
    visible.set()
    await asyncio.to_thread(fake.started.wait)
    await asyncio.to_thread(guard.join, 5)
    await snapshot.stop_ban_gate_snapshot()

    assert remote_bump_released_after_patch.is_set()
    assert fake.thread_id != get_ident()


@pytest.mark.asyncio
async def test_snapshot_remote_generation_get_does_not_block_and_refreshes_on_change(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.gen = 0
            self.calls = 0
            self.started = Event()
            self.release = Event()
            self.thread_id = None

        def get(self, _key):
            self.thread_id = get_ident()
            self.calls += 1
            value = self.gen
            if self.calls == 1:
                self.started.set()
                self.release.wait()
            return str(value).encode()

    fake = FakeRedis()
    heartbeat = Event()
    released_after_heartbeat = Event()
    refreshed_after_change = asyncio.Event()
    refresh_calls = 0

    async def refresh():
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls >= 3:
            refreshed_after_change.set()

    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    monkeypatch.setattr(snapshot, "refresh_ban_gate_snapshot", refresh)
    monkeypatch.setattr(snapshot, "_REMOTE_GEN_SYNC_TTL_SEC", 0.01)
    monkeypatch.setattr(snapshot, "_SNAPSHOT_REFRESH_SEC", 0.1)
    snapshot._synced_redis_gen = 0
    snapshot._remote_gen_checked_at = 0.0

    def release_guard() -> None:
        fake.started.wait(5)
        if heartbeat.wait(2):
            released_after_heartbeat.set()
        fake.release.set()

    guard = Thread(target=release_guard, daemon=True)
    guard.start()
    await snapshot.start_ban_gate_snapshot()
    await asyncio.wait_for(asyncio.to_thread(fake.started.wait), timeout=5)

    async def pulse() -> None:
        await asyncio.sleep(0)
        heartbeat.set()

    await pulse()
    fake.gen = 1
    fake.release.set()
    await asyncio.wait_for(refreshed_after_change.wait(), timeout=5)
    await snapshot.stop_ban_gate_snapshot()
    await asyncio.to_thread(guard.join, 5)

    assert released_after_heartbeat.is_set()
    assert fake.thread_id != get_ident()


@pytest.mark.asyncio
async def test_stop_joins_blocked_snapshot_io_and_restart_keeps_new_loop(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.calls = 0
            self.started = Event()
            self.release = Event()

        def get(self, _key):
            self.calls += 1
            if self.calls == 1:
                self.started.set()
                self.release.wait()
            return b"0"

    fake = FakeRedis()
    heartbeat = Event()
    early_release = Event()
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: fake,
    )
    monkeypatch.setattr(snapshot, "refresh_ban_gate_snapshot", AsyncMock())
    monkeypatch.setattr(snapshot, "_REMOTE_GEN_SYNC_TTL_SEC", 0.01)
    monkeypatch.setattr(snapshot, "_SNAPSHOT_REFRESH_SEC", 0.1)

    def release_guard() -> None:
        fake.started.wait(5)
        if not heartbeat.wait(2):
            early_release.set()
            fake.release.set()

    guard = Thread(target=release_guard, daemon=True)
    guard.start()
    await snapshot.start_ban_gate_snapshot()
    await asyncio.wait_for(asyncio.to_thread(fake.started.wait), timeout=5)

    async def pulse() -> None:
        await asyncio.sleep(0)
        heartbeat.set()

    await pulse()
    assert not early_release.is_set()
    stopping = asyncio.create_task(snapshot.stop_ban_gate_snapshot())
    await asyncio.sleep(0)
    assert not stopping.done()
    fake.release.set()
    await stopping
    assert snapshot._refresh_task is None

    await snapshot.start_ban_gate_snapshot()
    assert snapshot._refresh_task is not None
    await snapshot.stop_ban_gate_snapshot()
    await asyncio.to_thread(guard.join, 5)


@pytest.mark.asyncio
async def test_reset_does_not_accept_a_late_snapshot_refresh(monkeypatch):
    initial_users = frozenset({881_006})
    stale_users = frozenset({881_007})
    refresh_count = 0
    refresh_started = Event()
    release_refresh = asyncio.Event()

    async def load_snapshot():
        nonlocal refresh_count
        refresh_count += 1
        if refresh_count == 1:
            return initial_users, {}, frozenset()
        refresh_started.set()
        try:
            await release_refresh.wait()
        except asyncio.CancelledError:
            await release_refresh.wait()
        return stale_users, {}, frozenset()

    monkeypatch.setattr(snapshot, "get_db_backend", lambda: "postgresql")
    monkeypatch.setattr(snapshot, "_load_snapshot_postgresql", load_snapshot)

    await snapshot.start_ban_gate_snapshot()
    await asyncio.wait_for(asyncio.to_thread(refresh_started.wait), timeout=5)
    resetting = asyncio.create_task(snapshot.reset_ban_gate_snapshot_for_tests())
    await asyncio.sleep(0)
    assert not resetting.done()
    release_refresh.set()
    await resetting

    assert snapshot.is_user_globally_banned_fast(881_006) is None
    assert snapshot.is_user_globally_banned_fast(881_007) is None
    assert snapshot._refresh_task is None


@pytest.mark.asyncio
async def test_stop_drains_pending_bump_without_refreshing_after_restart(monkeypatch):
    started = Event()
    release = Event()
    finished = Event()

    class FakeRedis:
        def incr(self, _key):
            started.set()
            release.wait()
            finished.set()
            return 1

    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_claim.get_coord_redis_client",
        lambda: FakeRedis(),
    )
    refresh = AsyncMock()
    monkeypatch.setattr(snapshot, "refresh_ban_gate_snapshot", refresh)
    snapshot.schedule_ban_gate_snapshot_refresh()
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=5)
        stopping = asyncio.create_task(snapshot.stop_ban_gate_snapshot())
        await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, timeout=5)
        assert finished.is_set()
        refresh.assert_not_awaited()
        assert not snapshot._redis_io_tasks
        assert not snapshot._background_tasks

        await snapshot.start_ban_gate_snapshot()
        assert snapshot._refresh_task is not None
        await snapshot.stop_ban_gate_snapshot()
        assert not snapshot._redis_io_tasks
        assert not snapshot._background_tasks
    finally:
        release.set()
        await snapshot.stop_ban_gate_snapshot()


def mark_snapshot_ready() -> None:
    snapshot._ready = True
    snapshot._last_refresh_mono = time.monotonic()


def test_stale_snapshot_still_serves_last_successful_value(monkeypatch: pytest.MonkeyPatch) -> None:
    mark_snapshot_ready()
    snapshot._global_banned = frozenset({10001})
    monkeypatch.setattr(snapshot.time, "monotonic", lambda: snapshot._last_refresh_mono + 121.0)

    assert snapshot.is_user_globally_banned_fast(10001) is True
    assert snapshot.is_user_globally_banned_fast(10002) is False


@pytest.mark.asyncio
async def test_snapshot_status_reports_refresh_failure_without_dropping_last_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark_snapshot_ready()
    snapshot._global_banned = frozenset({10001})
    monkeypatch.setattr(snapshot, "get_db_backend", lambda: "postgresql")

    async def fail_load():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(snapshot, "_load_snapshot_postgresql", fail_load)

    await snapshot.refresh_ban_gate_snapshot()

    status = snapshot.ban_gate_snapshot_status()
    assert snapshot.is_user_globally_banned_fast(10001) is True
    assert status["ready"] is True
    assert status["refresh_failures"] == 1
    assert status["last_failure_age_sec"] is not None


@pytest.mark.asyncio
async def test_apply_user_banned_change_updates_fast_path(monkeypatch):
    from packages.blacklist import apply_user_banned_change, reset_user_ban_gate_cache

    monkeypatch.setattr(snapshot, "schedule_ban_gate_snapshot_refresh", lambda: None)
    await reset_user_ban_gate_cache()
    mark_snapshot_ready()
    uid = 881_001
    await apply_user_banned_change(uid, True)
    assert snapshot.is_user_globally_banned_fast(uid) is True

    await apply_user_banned_change(uid, False)
    assert snapshot.is_user_globally_banned_fast(uid) is False


@pytest.mark.asyncio
async def test_apply_group_blocked_users_change_updates_fast_path(monkeypatch):
    from packages.blacklist import apply_group_blocked_users_change, reset_group_ban_gate_cache

    monkeypatch.setattr(snapshot, "schedule_ban_gate_snapshot_refresh", lambda: None)
    await reset_group_ban_gate_cache()
    mark_snapshot_ready()
    gid = 881_002
    await apply_group_blocked_users_change(gid, [10001, 10002])
    assert snapshot.is_user_blocked_in_group_fast(gid, 10001) is True
    assert snapshot.is_user_blocked_in_group_fast(gid, 10003) is False

    await apply_group_blocked_users_change(gid, [])
    assert snapshot.is_user_blocked_in_group_fast(gid, 10001) is False


@pytest.mark.asyncio
async def test_apply_group_banned_change_updates_fast_path(monkeypatch):
    from packages.blacklist import apply_group_banned_change, reset_group_ban_gate_cache

    monkeypatch.setattr(snapshot, "schedule_ban_gate_snapshot_refresh", lambda: None)
    await reset_group_ban_gate_cache()
    mark_snapshot_ready()
    gid = 881_003
    await apply_group_banned_change(gid, True)
    assert snapshot.is_group_banned_fast(gid) is True

    await apply_group_banned_change(gid, False)
    assert snapshot.is_group_banned_fast(gid) is False
