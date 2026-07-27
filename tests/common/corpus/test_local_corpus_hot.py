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
async def test_aggregate_local_hot_keywords_mongo_uses_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mongo 路径用聚合取 top，避免 find_all 整表。"""
    import pallas.core.foundation.db.modules as modules
    from pallas.product.corpus import local_hot as mod

    pipelines: list[list] = []

    class _Agg:
        def __init__(self, pipeline):
            pipelines.append(pipeline)

        async def to_list(self, _n):
            if len(pipelines) == 1:
                return [{"_id": "你好", "score": 3}]
            return [
                {
                    "_id": "你好",
                    "answer_rows": [
                        {"answer_keywords": "早", "count": 3, "messages": ["早上好"]},
                    ],
                }
            ]

    class _Coll:
        def aggregate(self, pipeline):
            return _Agg(pipeline)

    class _FakeContext:
        @staticmethod
        def get_motor_collection():
            return _Coll()

    monkeypatch.setattr(modules, "Context", _FakeContext)

    rows = await mod.aggregate_local_hot_keywords_mongo(
        scope="global",
        group_id=None,
        limit=10,
        answers_per_keyword=3,
    )
    assert rows == [
        {
            "keywords": "你好",
            "score": 3,
            "answers": [{"answer_keywords": "早", "message": "早上好", "count": 3}],
        }
    ]
    assert len(pipelines) == 2
    assert pipelines[0][0] == {"$unwind": "$answers"}
