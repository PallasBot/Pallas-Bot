from __future__ import annotations

import asyncio

import pytest

from pallas.core.foundation.db.modules import Answer, Context
from pallas.product.corpus.config import CorpusConfig


@pytest.mark.asyncio
async def test_schedule_mirror_upsert_answer_uses_background_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.corpus import write_fanout as mod

    await mod.reset_corpus_write_runtime_state_for_tests()
    called: list[tuple[str, str]] = []

    async def fake_mirror_upsert_answer(**kwargs) -> None:
        called.append((kwargs["keywords"], kwargs["message"]))

    monkeypatch.setattr(mod, "mirror_upsert_answer", fake_mirror_upsert_answer)
    monkeypatch.setattr(mod, "community_contribute_enabled", lambda cfg: True)
    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.pg_pool_under_pressure", lambda threshold=0.75: False)

    cfg = CorpusConfig(community_contribute=True)
    mod.schedule_mirror_upsert_answer(
        fed=None,
        community=object(),
        cfg=cfg,
        keywords="kw",
        group_id=1,
        answer_keywords="ans",
        answer_time=99,
        message="msg",
        append_on_existing=True,
    )

    await asyncio.wait_for(mod.corpus_write_queue().join(), timeout=1.0)

    assert called == [("kw", "msg")]
    await mod.reset_corpus_write_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_schedule_mirror_insert_uses_background_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.corpus import write_fanout as mod

    await mod.reset_corpus_write_runtime_state_for_tests()
    called: list[str] = []

    async def fake_mirror_insert(**kwargs) -> None:
        called.append(kwargs["context"].keywords)

    monkeypatch.setattr(mod, "mirror_insert", fake_mirror_insert)
    monkeypatch.setattr(mod, "community_contribute_enabled", lambda cfg: True)
    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.pg_pool_under_pressure", lambda threshold=0.75: False)

    cfg = CorpusConfig(community_contribute=True)
    ctx = Context.model_construct(
        keywords="kw",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="a", group_id=1, count=1, time=1, messages=["hi"])],
        ban=[],
        clear_time=0,
    )

    mod.schedule_mirror_insert(
        fed=None,
        community=object(),
        cfg=cfg,
        context=ctx,
    )

    await asyncio.wait_for(mod.corpus_write_queue().join(), timeout=1.0)

    assert called == ["kw"]
    await mod.reset_corpus_write_runtime_state_for_tests()
