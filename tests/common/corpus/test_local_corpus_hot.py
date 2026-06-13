from __future__ import annotations

import pytest

from src.features.corpus.text_util import plain_message_text


def test_plain_message_text_strips_cq() -> None:
    assert plain_message_text("早啊[CQ:face,id=178]呀") == "早啊呀"


@pytest.mark.asyncio
async def test_aggregate_local_hot_keywords_empty_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import local_hot as mod

    monkeypatch.setattr(mod, "get_db_backend", lambda: "unknown")
    rows = await mod.aggregate_local_hot_keywords()
    assert rows == []


@pytest.mark.asyncio
async def test_build_local_corpus_hot_payload_shape() -> None:
    from src.features.corpus.local_hot import build_local_corpus_hot_payload

    payload = build_local_corpus_hot_payload(
        [{"keywords": "你好", "score": 3, "answers": [{"answer_keywords": "早", "message": "早", "count": 3}]}],
        as_of="2026-06-14T00:00:00Z",
    )
    assert payload["mode"] == "pool"
    assert payload["window_sec"] == 0
    assert payload["items"][0]["keywords"] == "你好"
