from __future__ import annotations

import pytest

from pallas.product.corpus.text_util import plain_message_text


def test_plain_message_text_strips_cq() -> None:
    assert plain_message_text("早啊[CQ:face,id=178]呀") == "早啊呀"


@pytest.mark.asyncio
async def test_aggregate_local_hot_keywords_empty_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.corpus import local_hot as mod

    monkeypatch.setattr(mod, "get_db_backend", lambda: "unknown")
    rows = await mod.aggregate_local_hot_keywords()
    assert rows == []


@pytest.mark.asyncio
async def test_build_local_corpus_hot_payload_shape() -> None:
    from pallas.product.corpus.local_hot import build_local_corpus_hot_payload

    payload = build_local_corpus_hot_payload(
        [{"keywords": "你好", "score": 3, "answers": [{"answer_keywords": "早", "message": "早", "count": 3}]}],
        as_of="2026-06-14T00:00:00Z",
    )
    assert payload["mode"] == "pool"
    assert payload["window_sec"] == 0
    assert payload["items"][0]["keywords"] == "你好"


@pytest.mark.asyncio
async def test_aggregate_local_hot_keywords_mongo_uses_single_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Beanie 2.x project() 只接受一个 projection model（issue #227）。"""
    import pallas.core.foundation.db.modules as modules
    from pallas.product.corpus import local_hot as mod

    calls: list[object] = []

    class _FakeFind:
        def project(self, projection_model):
            calls.append(projection_model)
            return self

        async def to_list(self):
            return []

    class _FakeContext:
        @staticmethod
        def find_all():
            return _FakeFind()

    monkeypatch.setattr(modules, "Context", _FakeContext)

    rows = await mod.aggregate_local_hot_keywords_mongo(
        scope="global",
        group_id=None,
        limit=10,
        answers_per_keyword=3,
    )
    assert rows == []
    assert len(calls) == 1
    assert getattr(calls[0], "__name__", "") == "_ContextHotProjection"
