from __future__ import annotations

import asyncio

import pytest

from src.common.shard.coord import cage_duel as mod


@pytest.mark.asyncio
async def test_run_shard_merges_self_across_workers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_coord_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "_COLLECT_SEC", 0.05)
    monkeypatch.setattr(mod, "_STABLE_SEC", 0.02)
    monkeypatch.setattr(mod, "_POST_COLLECT_GRACE_SEC", 0.05)

    async def shard_run(shard_id: int, self_bot: int) -> tuple[int, int] | None:
        monkeypatch.setattr(
            "src.common.shard.registry.config.get_shard_registry_settings",
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
