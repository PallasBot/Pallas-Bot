from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pallas.core.foundation.db.modules import Answer, Context
from pallas.core.foundation.db.repository import ContextRepositoryExistenceMixin
from pallas.product.corpus.composite_repo import CompositeContextRepository
from pallas.product.corpus.config import CorpusConfig


class FakeContextRepo(ContextRepositoryExistenceMixin):
    def __init__(self, *, label: str, contexts: dict[str, Context] | None = None) -> None:
        self.label = label
        self.contexts = contexts or {}
        self.upsert_calls: list[tuple] = []
        self.insert_calls: list[Context] = []

    async def find_by_keywords(self, keywords: str):
        return self.contexts.get(keywords)

    async def save(self, context):  # noqa: ARG002
        return None

    async def insert(self, context: Context) -> None:
        self.insert_calls.append(context)

    async def delete_expired(self, expiration, threshold):  # noqa: ARG002
        return None

    async def find_for_cleanup(self, trigger_threshold, expiration):  # noqa: ARG002
        return []

    async def upsert_answer(
        self,
        keywords,
        group_id,
        answer_keywords,
        answer_time,
        message,
        append_on_existing,
    ) -> None:
        self.upsert_calls.append((keywords, group_id, answer_keywords, answer_time, message, append_on_existing))

    async def replace_answers(self, keywords, answers, clear_time):  # noqa: ARG002
        return None

    async def append_ban(self, keywords, ban):  # noqa: ARG002
        return None

    async def find_ban_reply_target(self, group_id, reply_message):  # noqa: ARG002
        return None


@pytest.fixture
def corpus_cfg() -> CorpusConfig:
    return CorpusConfig(
        merge_order=["local", "community"],
        merge_strategy="merge_counts",
        community_contribute=True,
    )


@pytest.mark.asyncio
async def test_composite_find_merges_sources(corpus_cfg: CorpusConfig):
    from pallas.product.corpus.find_cache import reset_find_cache_for_tests

    await reset_find_cache_for_tests()
    local = FakeContextRepo(
        label="local",
        contexts={
            "kw": Context.model_construct(
                keywords="kw",
                time=1,
                trigger_count=1,
                answers=[Answer(keywords="a", group_id=1, count=2, time=1, messages=["a"])],
                ban=[],
                clear_time=0,
            )
        },
    )
    remote = FakeContextRepo(
        label="community",
        contexts={
            "kw": Context.model_construct(
                keywords="kw",
                time=2,
                trigger_count=1,
                answers=[
                    Answer(keywords="a", group_id=1, count=3, time=2, messages=["b"]),
                    Answer(keywords="c", group_id=0, count=1, time=2, messages=["c"]),
                ],
                ban=[],
                clear_time=0,
            )
        },
    )
    repo = CompositeContextRepository(local, community=remote, cfg=corpus_cfg)
    with (
        patch("pallas.product.corpus.composite_repo.remote_corpus_find_mode", lambda _cfg=None: "sync"),
        patch("pallas.product.corpus.remote_budget.should_skip_remote_corpus", return_value=False),
    ):
        ctx = await repo.find_by_keywords("kw")
    assert ctx is not None
    by_kw = {a.keywords: a for a in ctx.answers}
    assert by_kw["a"].count == 5
    assert by_kw["c"].keywords == "c"


@pytest.mark.asyncio
async def test_composite_upsert_writes_local_and_schedules_mirror(corpus_cfg: CorpusConfig):
    local = FakeContextRepo(label="local")
    remote = FakeContextRepo(label="community")
    repo = CompositeContextRepository(local, community=remote, cfg=corpus_cfg)
    with patch("pallas.product.corpus.composite_repo.schedule_mirror_upsert_answer") as mock_schedule:
        await repo.upsert_answer("kw", 1, "ans", 99, "msg", True)
    assert len(local.upsert_calls) == 1
    mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_local_first_skips_remote_when_local_has_answers():
    local = FakeContextRepo(
        label="local",
        contexts={
            "kw": Context.model_construct(
                keywords="kw",
                time=1,
                trigger_count=1,
                answers=[Answer(keywords="a", group_id=1, count=1, time=1, messages=["a"])],
                ban=[],
                clear_time=0,
            )
        },
    )
    remote = FakeContextRepo(label="community")
    remote.find_by_keywords = AsyncMock(return_value=None)  # type: ignore[method-assign]
    cfg = CorpusConfig(merge_order=["local", "community"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, community=remote, cfg=cfg)
    ctx = await repo.find_by_keywords("kw")
    assert ctx is not None
    remote.find_by_keywords.assert_not_called()


@pytest.mark.asyncio
async def test_local_context_exists_does_not_hit_remote():
    local = FakeContextRepo(label="local", contexts={})
    remote = FakeContextRepo(label="community")
    remote.context_exists_by_keywords = AsyncMock(return_value=True)  # type: ignore[method-assign]
    cfg = CorpusConfig(merge_order=["local", "community"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, community=remote, cfg=cfg)
    assert await repo.local_context_exists_by_keywords("kw") is False
    remote.context_exists_by_keywords.assert_not_called()


@pytest.mark.asyncio
async def test_composite_remote_find_failure_degrades(corpus_cfg: CorpusConfig):
    from pallas.product.corpus.find_cache import reset_find_cache_for_tests

    await reset_find_cache_for_tests()
    local = FakeContextRepo(
        label="local",
        contexts={
            "kw": Context.model_construct(
                keywords="kw",
                time=1,
                trigger_count=1,
                answers=[Answer(keywords="a", group_id=1, count=1, time=1, messages=["a"])],
                ban=[],
                clear_time=0,
            )
        },
    )
    remote = FakeContextRepo(label="community")
    remote.find_by_keywords = AsyncMock(side_effect=RuntimeError("network"))  # type: ignore[method-assign]
    repo = CompositeContextRepository(local, community=remote, cfg=corpus_cfg)
    with (
        patch("pallas.product.corpus.composite_repo.remote_corpus_find_mode", lambda _cfg=None: "sync"),
        patch("pallas.product.corpus.remote_budget.should_skip_remote_corpus", return_value=False),
    ):
        ctx = await repo.find_by_keywords("kw")
    assert ctx is not None
    assert len(ctx.answers) == 1


@pytest.mark.asyncio
async def test_maybe_wrap_composite_disabled(monkeypatch):
    from pallas.product.corpus import factory as factory_mod

    monkeypatch.setattr(factory_mod, "corpus_composite_enabled", lambda: False)
    local = FakeContextRepo(label="local")
    wrapped = factory_mod.maybe_wrap_composite(local)
    assert wrapped is local
