from __future__ import annotations

import pytest

from src.platform.shard.coord import group_activity as ga_mod


def spy_lock() -> ga_mod.GroupActivityLock:
    return ga_mod.get_group_activity_lock(
        "spy_group",
        session_extra_keys=frozenset({"session_active"}),
        is_live_session=lambda data: ga_mod.session_live_by_flag(data, flag_key="session_active"),
    )


def test_spy_group_lock_exclusive(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(ga_mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        ga_mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = spy_lock()
    assert lock.try_begin(10086) is True
    assert lock.try_begin(10086) is False
    lock.end(10086)
    assert lock.try_begin(10086) is True


def test_spy_group_local_fallback(monkeypatch) -> None:
    monkeypatch.setattr(ga_mod, "is_sharding_active", lambda: False)
    lock = spy_lock()
    lock.local_busy.clear()
    assert lock.try_begin(1) is True
    assert lock.try_begin(1) is False
    lock.end(1)
    assert lock.try_begin(1) is True
    lock.end(1)


@pytest.mark.asyncio
async def test_reclaim_orphan_spy_group_without_session(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(ga_mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        ga_mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = spy_lock()
    lock.orphan_min_age_sec = 0.0

    assert lock.try_begin(42) is True
    assert lock.try_begin(42) is False
    data = lock.read(42) or {}
    data["acquired_at"] = 1.0
    lock.store(42, data)
    assert lock.is_orphan_lock(lock.read(42)) is True
    assert await lock.try_reclaim_orphan(42, has_local=False) is True
    assert lock.try_begin(42) is True
    lock.end(42)


def test_spy_prep_room_metadata(fake_coord_redis, monkeypatch) -> None:
    from src.plugins.who_is_spy.group_lock import mark_spy_prep_room, read_spy_prep_room

    monkeypatch.setattr(ga_mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        ga_mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = spy_lock()
    assert lock.try_begin(9001) is True
    mark_spy_prep_room(9001, owner_id=3023094357, host_bot_id=2927116873)
    prep = read_spy_prep_room(9001)
    assert prep == (3023094357, 2927116873)
    lock.end(9001)
    assert read_spy_prep_room(9001) is None


def test_spy_prep_players_and_snapshot(fake_coord_redis, monkeypatch) -> None:
    from src.plugins.who_is_spy.coord_store import read_prep_players, write_game_snapshot, write_prep_players
    from src.plugins.who_is_spy.models import Game, Player

    monkeypatch.setattr(ga_mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        ga_mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = ga_mod.get_group_activity_lock(
        "spy_group",
        session_extra_keys=frozenset(
            {"session_active", "prep_owner_id", "prep_host_bot_id", "prep_players", "game_snapshot"}
        ),
        is_live_session=lambda data: ga_mod.session_live_by_flag(data, flag_key="session_active"),
    )
    assert lock.try_begin(9002) is True

    game = Game(group_id=9002, owner_id=1)
    game.players[1] = Player(uid=1, nickname="A")
    game.players[2] = Player(uid=2, nickname="B")
    write_prep_players(9002, game)
    assert read_prep_players(9002) == [(1, "A"), (2, "B")]

    game.ready = True
    game.alive_order = [1, 2]
    write_game_snapshot(game)
    lock.end(9002)


@pytest.mark.asyncio
async def test_reclaim_skips_live_session(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(ga_mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        ga_mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    lock = spy_lock()
    lock.orphan_min_age_sec = 0.0

    assert lock.try_begin(7) is True
    lock.mark_session(7, session_active=True)
    data = lock.read(7) or {}
    data["acquired_at"] = 1.0
    lock.store(7, data)
    assert await lock.try_reclaim_orphan(7, has_local=False) is False
    lock.end(7)
