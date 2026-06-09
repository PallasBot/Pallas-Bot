from __future__ import annotations

import time

from src.platform.shard.coord import cage_duel as mod


def test_cross_shard_pair_finalize(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.platform.shard.registry.config.get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 2})(),
    )

    path = mod._session_path(626266902, 88001)
    seed = "626266902:3415750178:1715923490"

    def init(data: dict) -> None:
        data.update({
            "group_id": 626266902,
            "collect_until": time.time() - 0.01,
            "shards": {"2": [923722427], "3": [3879348674], "5": [2927116873]},
            "pair": None,
        })

    mod._mutate_session(path, init)
    mod._register_shard_bots(path, 2, [923722427])
    mod._register_shard_bots(path, 3, [3879348674])
    mod._register_shard_bots(path, 5, [2927116873])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)
    mod._try_finalize_pair(path, 923722427, seed)
    pair = mod._read_session(path).get("pair")
    assert isinstance(pair, list)
    assert len(pair) == 2
    assert set(pair) <= {923722427, 3879348674, 2927116873}


def test_finalize_only_by_min_registered_bot(fake_coord_redis) -> None:
    path = mod._session_path(100, 1)
    seed = "1"

    def init(data: dict) -> None:
        data.update({
            "collect_until": time.time() - 0.01,
            "shards": {"0": [500], "1": [100, 200]},
            "pair": None,
        })

    mod._mutate_session(path, init)
    mod._register_shard_bots(path, 0, [500])
    mod._register_shard_bots(path, 1, [100, 200])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)
    mod._try_finalize_pair(path, 500, seed)
    assert mod._read_session(path).get("pair") is None
    mod._try_finalize_pair(path, 100, seed)
    pair = mod._read_session(path).get("pair")
    assert isinstance(pair, list)
    assert set(pair) == {100, 200, 500} or set(pair) <= {100, 200, 500}
    assert len(pair) == 2
