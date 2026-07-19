from __future__ import annotations

import pytest

from pallas.core.platform.multi_bot.dedup import (
    ingress_shard_claim_owner_obsolete,
    try_claim_cross_bot_message_memory,
    try_claim_cross_shard_message,
)


@pytest.mark.asyncio
async def test_cross_shard_claim_one_shard_wins() -> None:
    plugin = "test_ingress_shard"
    gid, uid, body, t = 1, 2, "hello", 100
    assert await try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=0)
    assert await try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=0)
    assert not await try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=1)


@pytest.mark.asyncio
async def test_ingress_shard_claim_scoped_by_message_time() -> None:
    plugin = "test_ingress_shard_time"
    gid, uid, body = 626266902, 3023094357, "牛牛唱歌"
    assert await try_claim_cross_shard_message(plugin, gid, uid, body, 100, shard_id=3, include_message_time=True)
    assert await try_claim_cross_shard_message(plugin, gid, uid, body, 101, shard_id=6, include_message_time=True)
    assert not await try_claim_cross_shard_message(plugin, gid, uid, body, 100, shard_id=6, include_message_time=True)


@pytest.mark.asyncio
async def test_ingress_bot_claim_scoped_by_message_time() -> None:
    plugin = "test_ingress_bot_time"
    gid, uid, body = 626266902, 3023094357, "牛牛唱歌"
    assert await try_claim_cross_bot_message_memory(plugin, gid, uid, body, 100, 111, include_message_time=True)
    assert await try_claim_cross_bot_message_memory(plugin, gid, uid, body, 101, 222, include_message_time=True)
    assert not await try_claim_cross_bot_message_memory(plugin, gid, uid, body, 100, 222, include_message_time=True)


@pytest.mark.asyncio
async def test_ingress_shard_claim_reclaims_obsolete_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.multi_bot import dedup as mod

    mod._shard_ingress_file_locks.clear()
    mod._cross_bot_claim_owners.clear()

    plugin = "test_ingress_shard_obsolete"
    gid, uid, body, t = 1, 2, "牛牛唱歌", 100

    class FakeShard:
        id = 0

    class FakeReg:
        shards = [FakeShard()]

    owner_by_key: dict[tuple[str, int, int], int] = {}

    def fake_read_claim_owner_sync(plugin: str, group_id: int, message_id: int) -> int | None:
        return owner_by_key.get((plugin, group_id, message_id))

    async def fake_try_claim_message(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
        key = (plugin, group_id, message_id)
        owner = owner_by_key.get(key)
        if owner is None:
            owner_by_key[key] = int(bot_id)
            return True
        return owner == int(bot_id)

    async def fake_take_claim_message(plugin: str, group_id: int, message_id: int, bot_id: int) -> bool:
        owner_by_key[(plugin, group_id, message_id)] = int(bot_id)
        return True

    monkeypatch.setattr("pallas.core.platform.shard.registry.get_shard_registry", lambda: FakeReg())
    monkeypatch.setattr("pallas.core.platform.multi_bot.dedup.read_claim_owner_sync", fake_read_claim_owner_sync)
    monkeypatch.setattr("pallas.core.platform.multi_bot.dedup.try_claim_message", fake_try_claim_message)
    monkeypatch.setattr("pallas.core.platform.multi_bot.claim.take_claim_message", fake_take_claim_message)
    assert ingress_shard_claim_owner_obsolete(99)
    assert not ingress_shard_claim_owner_obsolete(0)

    assert await mod.try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=99, include_message_time=True)
    assert await mod.try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=0, include_message_time=True)
