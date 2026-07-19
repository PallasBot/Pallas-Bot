from __future__ import annotations

import pytest

from pallas.core.platform.shard.local_representative import (
    is_local_worker_representative,
    local_worker_representative_bot_id,
)


def test_local_worker_representative_bot_id(monkeypatch):
    monkeypatch.setattr(
        "nonebot.get_bots",
        lambda: {"300": object(), "100": object(), "200": object()},
    )
    assert local_worker_representative_bot_id() == 100


def test_is_local_worker_representative(monkeypatch):
    monkeypatch.setattr(
        "nonebot.get_bots",
        lambda: {"300": object(), "100": object()},
    )
    assert is_local_worker_representative(100)
    assert not is_local_worker_representative(300)


@pytest.mark.asyncio
async def test_cross_shard_claim_one_file_claim_per_worker(monkeypatch) -> None:
    monkeypatch.setattr(
        "nonebot.get_bots",
        lambda: {"100": object(), "200": object()},
    )
    from pallas.core.platform.multi_bot import dedup as mod

    mod._shard_ingress_file_locks.clear()
    mod._cross_bot_claim_owners.clear()

    plugin = "test_ingress_shard_rep"
    gid, uid, body, t = 1, 2, "hello", 100
    assert await mod.try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=0, bot_id=100)
    assert await mod.try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=0, bot_id=200)
    assert not await mod.try_claim_cross_shard_message(plugin, gid, uid, body, t, shard_id=1, bot_id=100)
