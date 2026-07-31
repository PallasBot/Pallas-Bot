from __future__ import annotations

import json
import threading
import time

from pallas.product.llm.knowledge import embed_redis as er


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self._cond = threading.Condition()

    def get(self, key: str):
        return self.kv.get(key)

    def setex(self, key: str, ttl: int, value: str) -> bool:
        del ttl
        self.kv[key] = value
        with self._cond:
            self._cond.notify_all()
        return True

    def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        with self._cond:
            self._cond.notify_all()
        return len(self.lists[key])

    def brpop(self, keys, timeout: int = 0):
        key = keys[0] if isinstance(keys, (list, tuple)) else keys
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while True:
                items = self.lists.get(key) or []
                if items:
                    return key, items.pop()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=remaining)


def test_embed_vec_key_stable(monkeypatch) -> None:
    monkeypatch.setattr(er, "redis_client_or_none", lambda: None)
    k1 = er.embed_vec_key("BAAI/bge-small-zh-v1.5", "你好")
    k2 = er.embed_vec_key("BAAI/bge-small-zh-v1.5", "你好")
    assert k1 == k2
    assert k1.startswith("pallas:embed:v1:vec:")


def test_get_set_cached_vec_roundtrip(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(er, "redis_client_or_none", lambda: fake)
    assert er.get_cached_vec("m", "hello") is None
    er.set_cached_vec("m", "hello", [0.1, 0.2], kind="query")
    assert er.get_cached_vec("m", "hello") == [0.1, 0.2]


def test_enqueue_and_wait_reply(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(er, "redis_client_or_none", lambda: fake)

    def worker() -> None:
        item = fake.brpop([er.JOBS_KEY], timeout=2)
        assert item is not None
        _key, raw = item
        job = json.loads(raw)
        er.complete_embed_job(job, [[1.0, 2.0]])

    threading.Thread(target=worker, daemon=True).start()
    vecs = er.request_embeddings(["hi"], model="m", timeout_sec=2.0)
    assert vecs == [[1.0, 2.0]]
    assert er.get_cached_vec("m", "hi") == [1.0, 2.0]
