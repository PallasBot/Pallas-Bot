from __future__ import annotations

import random

from src.plugins.duel.duel_bots import cage_pair_seed, pick_cage_duel_bot_pair


def test_cage_pair_seed_same_across_message_ids() -> None:
    gid, uid, t = 733291779, 3415750178, 1715923506
    assert cage_pair_seed(gid, uid, t) == cage_pair_seed(gid, uid, t)
    assert cage_pair_seed(gid, uid, t) != cage_pair_seed(gid, uid, t + 1)


def test_cage_pair_deterministic_on_same_population() -> None:
    ids = [111, 222, 333, 923722427, 2927116873]
    seed = cage_pair_seed(626266902, 3415750178, 1715923490)
    p1 = tuple(sorted(random.Random(seed).sample(ids, 2)))
    p2 = tuple(sorted(random.Random(seed).sample(ids, 2)))
    assert p1 == p2


async def test_pick_cage_uses_group_online_list(monkeypatch) -> None:
    async def fake_online(group_id: int) -> list[int]:
        assert group_id == 42
        return [111, 222, 333]

    monkeypatch.setattr("src.plugins.duel.duel_bots.list_group_online_bot_ids", fake_online)
    pair = await pick_cage_duel_bot_pair(42, 99, 1000)
    assert pair is not None
    allowed = (111, 222, 333)
    assert pair[0] in allowed
    assert pair[1] in allowed
