from __future__ import annotations

import time

import pytest

from src.common.shard.coord import maa_seen_registry as mod


def test_touch_and_was_seen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_seen_dir", lambda: tmp_path)
    user = "123456789"
    device = "42cfa6e9-dfa1-47d8-a7c1-d9a6d658b06d"
    mod.touch_maa_seen_sync(user, device)
    assert mod.was_maa_seen_sync(user, device, ttl=3600)
    assert mod.was_maa_seen_sync(user, "42cfa6e9dfa147d8a7c1d9a6d658b06d", ttl=3600)


@pytest.mark.asyncio
async def test_store_was_seen_reads_cluster_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_seen_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "src.common.shard.registry.config.is_sharding_active",
        lambda: True,
    )
    from src.plugins.maa.store import MaaStore

    store = MaaStore()
    user = "999"
    device = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    mod.touch_maa_seen_sync(user, device)
    assert await store.was_seen(user, device, ttl=3600)
