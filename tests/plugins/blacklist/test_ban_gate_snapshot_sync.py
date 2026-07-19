from __future__ import annotations

import time

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


def mark_snapshot_ready() -> None:
    snapshot._ready = True
    snapshot._last_refresh_mono = time.monotonic()


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
