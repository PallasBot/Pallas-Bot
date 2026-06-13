from __future__ import annotations

import pytest

from src.foundation.db.modules import Answer, Context


@pytest.mark.asyncio
async def test_backfill_cursor_advances(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.features.corpus import backfill as mod
    from src.features.corpus.backfill_store import load_backfill_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "corpus_backfill_enabled", lambda: True)
    monkeypatch.setattr(mod, "should_run_corpus_backfill", lambda: True)
    monkeypatch.setattr(mod, "backfill_should_skip_pressure", lambda: False)
    monkeypatch.setattr(mod, "consume_backfill_rate_slot", lambda: True)

    contexts = [
        Context.model_construct(
            keywords="alpha",
            time=1,
            trigger_count=1,
            answers=[Answer(keywords="a1", group_id=1, count=2, time=1, messages=["hi"])],
            ban=[],
            clear_time=0,
        ),
        Context.model_construct(
            keywords="beta",
            time=2,
            trigger_count=1,
            answers=[Answer(keywords="b1", group_id=2, count=1, time=2, messages=["yo"])],
            ban=[],
            clear_time=0,
        ),
    ]

    async def fake_page(*, after_keywords: str, limit: int):
        if after_keywords:
            return contexts[1:]
        return contexts[:1]

    pushed: list[str] = []

    class FakeCommunity:
        async def upsert_answer(self, **kwargs) -> None:
            pushed.append(str(kwargs.get("keywords")))

    monkeypatch.setattr(mod, "list_local_contexts_page", fake_page)
    monkeypatch.setattr(mod, "build_community_repository", lambda: FakeCommunity())

    await mod.run_corpus_backfill_round()
    state = load_backfill_state()
    assert state.get("cursor_keywords") == "alpha"
    assert pushed == ["alpha"]

    await mod.run_corpus_backfill_round()
    state = load_backfill_state()
    assert state.get("cursor_keywords") == "beta"
    assert "beta" in pushed
