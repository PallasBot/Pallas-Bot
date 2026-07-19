from __future__ import annotations

import asyncio
import time

import pytest

from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key
from pallas.core.platform.shard.coord import cage_duel as mod
from pallas.core.platform.shard.coord.coord_redis_store import setex_json_sync


@pytest.mark.asyncio
async def test_run_shard_merges_self_across_workers(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_COLLECT_SEC", 0.05)
    monkeypatch.setattr(mod, "_STABLE_SEC", 0.02)
    monkeypatch.setattr(mod, "_POST_COLLECT_GRACE_SEC", 0.05)

    async def shard_run(shard_id: int, self_bot: int) -> tuple[int, int] | None:
        monkeypatch.setattr(
            "pallas.core.platform.shard.registry.config.get_shard_registry_settings",
            lambda: type("S", (), {"shard_id": shard_id})(),
        )
        return await mod.run_shard_cage_duel_coord(
            group_id=626266902,
            user_id=1,
            message_time=1000,
            plaintext="八角笼牛",
            self_bot_id=self_bot,
        )

    tasks = [
        asyncio.create_task(shard_run(2, 923722427)),
        asyncio.create_task(shard_run(3, 3879348674)),
        asyncio.create_task(shard_run(5, 2927116873)),
    ]
    results = await asyncio.gather(*tasks)
    assert any(r is not None for r in results)
    for r in results:
        if r is not None:
            assert set(r) <= {923722427, 3879348674, 2927116873}
            assert len(r) == 2


@pytest.mark.asyncio
async def test_cage_session_resets_after_completed_round(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_COLLECT_SEC", 0.05)
    monkeypatch.setattr(mod, "_STABLE_SEC", 0.02)
    monkeypatch.setattr(mod, "_POST_COLLECT_GRACE_SEC", 0.05)

    group_id = 626266902
    user_id = 1
    claim_key = cross_bot_group_message_key(
        group_id, user_id, "八角笼牛", 1000, use_plaintext=True, include_message_time=True
    )
    session_key = mod._session_path(group_id, claim_key)
    stale = {
        "group_id": group_id,
        "user_id": user_id,
        "message_time": 1000,
        "seed": "old",
        "collect_until": time.time() - 60,
        "shards": {"0": [111, 222]},
        "pair": [111, 222],
    }
    setex_json_sync(session_key, stale, mod._SESSION_TTL_SEC)

    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    pair = await mod.run_shard_cage_duel_coord(
        group_id=group_id,
        user_id=user_id,
        message_time=2000,
        plaintext="八角笼牛",
        self_bot_id=111,
    )
    path_new = mod._session_path(
        group_id,
        cross_bot_group_message_key(group_id, user_id, "八角笼牛", 2000, use_plaintext=True, include_message_time=True),
    )
    data = mod._read_session(path_new)
    assert data is not None
    assert data.get("message_time") == 2000
    assert data.get("pair") is None or pair is not None
