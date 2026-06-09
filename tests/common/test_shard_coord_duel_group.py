from __future__ import annotations

import pytest

from src.platform.shard.coord import duel_group as mod


def test_duel_group_lock_exclusive(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    assert mod.try_begin_duel_group(10086) is True
    assert mod.try_begin_duel_group(10086) is False
    mod.end_duel_group(10086)
    assert mod.try_begin_duel_group(10086) is True


def test_duel_group_local_fallback(monkeypatch):
    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    mod._local_busy.clear()
    assert mod.try_begin_duel_group(1) is True
    assert mod.try_begin_duel_group(1) is False
    mod.end_duel_group(1)
    assert mod.try_begin_duel_group(1) is True
    mod.end_duel_group(1)


@pytest.mark.asyncio
async def test_reclaim_orphan_duel_group_without_session(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    monkeypatch.setattr(mod, "_ORPHAN_BUSY_MIN_AGE_SEC", 0.0)

    assert mod.try_begin_duel_group(42) is True
    assert mod.try_begin_duel_group(42) is False
    data = mod._read(42) or {}
    data["acquired_at"] = 1.0
    mod._write_atomic(42, data)
    assert mod.is_orphan_duel_group_lock(mod._read(42)) is True
    assert await mod.try_reclaim_orphan_duel_group(42) is True
    assert mod.try_begin_duel_group(42) is True
    mod.end_duel_group(42)


@pytest.mark.asyncio
async def test_reclaim_skips_live_session(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    monkeypatch.setattr(mod, "_ORPHAN_BUSY_MIN_AGE_SEC", 0.0)

    assert mod.try_begin_duel_group(7) is True
    mod.mark_duel_group_session(7, 100, 200)
    data = mod._read(7) or {}
    data["acquired_at"] = 1.0
    mod._write_atomic(7, data)
    assert await mod.try_reclaim_orphan_duel_group(7) is False
    mod.end_duel_group(7)
