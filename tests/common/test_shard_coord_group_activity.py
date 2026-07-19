from __future__ import annotations

import pytest

from pallas.core.platform.shard.coord import group_activity as mod


def test_group_activity_lock_exclusive(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = mod.get_group_activity_lock("test_activity")
    assert lock.try_begin(1001) is True
    assert lock.try_begin(1001) is False
    lock.end(1001)
    assert lock.try_begin(1001) is True


@pytest.mark.asyncio
async def test_begin_group_activity_reclaims_orphan(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = mod.get_group_activity_lock("test_begin")
    lock.orphan_min_age_sec = 0.0
    assert lock.try_begin(9) is True
    data = lock.read(9) or {}
    data["acquired_at"] = 1.0
    lock.store(9, data)
    assert lock.try_begin(9) is False
    assert await mod.begin_group_activity(lock, 9) == "ok"
    lock.end(9)
