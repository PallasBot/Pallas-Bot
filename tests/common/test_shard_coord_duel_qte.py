from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from src.platform.shard.coord import duel_qte as mod
from src.platform.shard.coord import duel_qte_redis as redis_mod


@pytest.fixture
def fake_redis(monkeypatch):
    store: dict[str, str] = {}
    pub: list[str] = []

    class FakePipeline:
        def __init__(self, outer: FakeRedis, *, transaction: bool = False) -> None:
            self.outer = outer
            self.ops: list[tuple[str, tuple, dict]] = []

        def __enter__(self) -> FakePipeline:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def watch(self, key: str) -> None:
            pass

        def unwatch(self) -> None:
            pass

        def setex(self, key: str, ttl: int, val: str) -> None:
            self.ops.append(("setex", (key, ttl, val), {}))

        def publish(self, channel: str, body: str) -> None:
            self.ops.append(("publish", (channel, body), {}))

        def multi(self) -> None:
            pass

        def set(self, key: str, val: str, ex: int | None = None) -> None:
            self.ops.append(("set", (key, val), {"ex": ex}))

        def execute(self) -> list[Any]:
            results: list[Any] = []
            for op, args, kw in self.ops:
                if op == "setex":
                    results.append(self.outer.setex(*args))
                elif op == "publish":
                    results.append(self.outer.publish(*args))
                elif op == "set":
                    key, val = args
                    results.append(self.outer.set(key, val, ex=kw.get("ex")))
            self.ops.clear()
            return results

    class FakeRedis:
        def get(self, key: str):
            return store.get(key)

        def setex(self, key: str, ttl: int, val: str) -> bool:
            store[key] = val
            return True

        def set(self, key: str, val: str, ex: int | None = None, nx: bool = False) -> bool:
            if nx and key in store:
                return False
            store[key] = val
            return True

        def publish(self, channel: str, body: str) -> int:
            pub.append(body)
            return 1

        def pipeline(self, transaction: bool = True) -> FakePipeline:
            return FakePipeline(self, transaction=transaction)

    client = FakeRedis()
    monkeypatch.setattr("src.platform.coord.redis_settings.coord_redis_enabled", lambda: True)
    monkeypatch.setattr("src.platform.coord.redis_claim.get_coord_redis_client", lambda: client)
    return store, pub


def test_single_qte_cross_shard_result(fake_redis) -> None:
    store, _pub = fake_redis
    session_id = mod.publish_single_qte_request(
        group_id=10086,
        responder="200",
        required_key="格挡",
        window_sec=8,
        qte_kind="keyword",
        decoy_keys=None,
        deadline=time.time() + 5.0,
    )
    redis_mod.write_single_result_redis_sync(session_id, success=True)

    async def run() -> None:
        fut = asyncio.get_running_loop().create_future()
        await mod.wait_single_qte_coord_result(session_id, fut, deadline=time.time() + 2.0)
        assert fut.done()
        assert fut.result() is True

    asyncio.run(run())
    assert redis_mod.session_redis_key(session_id) in store


def test_race_qte_first_winner(fake_redis) -> None:
    mod.publish_race_qte_request(
        group_id=10086,
        challenger_id="100",
        defender_id="200",
        required_key="闪避",
        window_sec=8,
        qte_kind="keyword",
        decoy_keys=None,
        deadline=time.time() + 5.0,
    )
    sid = mod.race_qte_session_id(10086)
    assert redis_mod.try_write_race_winner_redis_sync(sid, winner_uid="100") is True
    assert redis_mod.try_write_race_winner_redis_sync(sid, winner_uid="200") is False
    data = redis_mod.read_session_redis_sync(sid)
    assert data is not None
    assert data.get("winner_uid") == "100"


def test_store_session_publishes_wake(fake_redis) -> None:
    _store, pub = fake_redis
    assert redis_mod.store_session_redis_sync(
        "r_10086",
        {"deadline": time.time() + 10, "kind": "race"},
    )
    assert any('"session_id":"r_10086"' in body for body in pub)
