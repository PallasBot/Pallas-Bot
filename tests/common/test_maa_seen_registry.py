from __future__ import annotations

import pytest

from src.platform.shard.coord import maa_seen_registry as mod


def test_touch_and_was_seen(fake_coord_redis) -> None:
    mod.clear_seen_cache_for_tests()
    user = "123456789"
    device = "42cfa6e9-dfa1-47d8-a7c1-d9a6d658b06d"
    mod.touch_maa_seen_sync(user, device)
    assert mod.was_maa_seen_sync(user, device, ttl=3600)
    assert mod.was_maa_seen_sync(user, "42cfa6e9dfa147d8a7c1d9a6d658b06d", ttl=3600)


def test_touch_updates_redis(fake_coord_redis) -> None:
    mod.clear_seen_cache_for_tests()
    user = "123456789"
    device = "42cfa6e9-dfa1-47d8-a7c1-d9a6d658b06d"
    mod.touch_maa_seen_sync(user, device)
    key = mod._seen_redis_key(user, device)
    assert key is not None
    assert key in fake_coord_redis[0]
    mod.touch_maa_seen_sync(user, device)
    assert mod.was_maa_seen_sync(user, device, ttl=3600)
    mod.flush_dirty_maa_seen_sync()


@pytest.mark.asyncio
async def test_store_was_seen_reads_cluster_redis(fake_coord_redis, monkeypatch) -> None:
    mod.clear_seen_cache_for_tests()
    monkeypatch.setattr(
        "src.platform.shard.context.is_sharding_active",
        lambda: True,
    )
    from src.plugins.maa.store import MaaStore

    store = MaaStore()
    user = "999"
    device = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    mod.touch_maa_seen_sync(user, device)
    assert await store.was_seen(user, device, ttl=3600)
