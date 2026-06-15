from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.features.corpus.composite_repo import CompositeContextRepository
from src.features.corpus.config import CorpusConfig, remote_corpus_find_mode
from src.features.corpus.prefetch import (
    import_remote_context_to_local,
    prefetch_concurrency,
    schedule_corpus_prefetch,
)
from src.foundation.db.modules import Answer, Context


def test_remote_find_true_maps_to_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.features.corpus.config.setting_str",
        lambda name, default="": "true" if name == "PALLAS_CORPUS_REMOTE_FIND_ENABLED" else default,
    )
    from src.features.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    assert remote_corpus_find_mode() == "prefetch"


def test_remote_find_sync_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.features.corpus.config.setting_str",
        lambda name, default="": "sync" if name == "PALLAS_CORPUS_REMOTE_FIND_ENABLED" else default,
    )
    from src.features.corpus.config import clear_corpus_config_cache

    clear_corpus_config_cache()
    assert remote_corpus_find_mode() == "sync"


@pytest.mark.asyncio
async def test_find_for_reply_prefetch_schedules_on_local_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus.find_cache import reset_find_cache_for_tests

    await reset_find_cache_for_tests()
    scheduled: list[str] = []

    def capture_schedule(keywords: str) -> None:
        scheduled.append(keywords)

    local = AsyncMock()
    local.find_by_keywords_for_reply = AsyncMock(return_value=None)
    community = AsyncMock()
    cfg = CorpusConfig(merge_order=["local", "community"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, community=community, cfg=cfg)

    import src.features.corpus.composite_repo as mod

    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda _cfg=None: "prefetch")
    monkeypatch.setattr("src.features.corpus.prefetch.schedule_corpus_prefetch", capture_schedule)

    assert await repo.find_by_keywords_for_reply("你好") is None
    assert scheduled == ["你好"]
    community.find_by_keywords.assert_not_called()


@pytest.mark.asyncio
async def test_find_for_reply_prefetch_returns_local_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus.find_cache import reset_find_cache_for_tests

    await reset_find_cache_for_tests()
    ctx = Context.model_construct(
        keywords="你好",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="啊", group_id=1, count=2, time=1, messages=["嗯"])],
        ban=[],
        clear_time=0,
    )
    local = AsyncMock()
    local.find_by_keywords_for_reply = AsyncMock(return_value=ctx)
    cfg = CorpusConfig(merge_order=["local"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, cfg=cfg)

    import src.features.corpus.composite_repo as mod

    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda _cfg=None: "prefetch")

    got = await repo.find_by_keywords_for_reply("你好")
    assert got is ctx


@pytest.mark.asyncio
async def test_find_for_reply_prefetch_uses_cache_on_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus.find_cache import reset_find_cache_for_tests

    await reset_find_cache_for_tests()
    ctx = Context.model_construct(
        keywords="你好",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="啊", group_id=1, count=2, time=1, messages=["嗯"])],
        ban=[],
        clear_time=0,
    )
    local = AsyncMock()
    local.find_by_keywords_for_reply = AsyncMock(return_value=ctx)
    cfg = CorpusConfig(merge_order=["local"], merge_strategy="local_first")
    repo = CompositeContextRepository(local, cfg=cfg)

    import src.features.corpus.composite_repo as mod

    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda _cfg=None: "prefetch")

    assert await repo.find_by_keywords_for_reply("你好") is ctx
    assert await repo.find_by_keywords_for_reply("你好") is ctx
    local.find_by_keywords_for_reply.assert_awaited_once_with("你好")


@pytest.mark.asyncio
async def test_schedule_prefetch_noop_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "off")
    schedule_corpus_prefetch("kw")
    assert mod.prefetch_queue().empty()


@pytest.mark.asyncio
async def test_schedule_prefetch_skips_when_learn_queue_under_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "prefetch")
    monkeypatch.setattr("src.plugins.repeater.learn_queue.learn_queue_under_pressure", lambda: True)

    schedule_corpus_prefetch("kw")

    assert mod.prefetch_queue().empty()


@pytest.mark.asyncio
async def test_schedule_prefetch_skips_when_pg_under_light_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "prefetch")
    monkeypatch.setattr("src.foundation.db.pool_budget.pg_pool_under_pressure", lambda threshold=0.75: threshold <= 0.15)

    schedule_corpus_prefetch("kw")

    assert mod.prefetch_queue().empty()


@pytest.mark.asyncio
async def test_schedule_prefetch_short_keyword_requires_repeat_before_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "prefetch")
    monkeypatch.setattr(mod, "should_skip_corpus_prefetch", lambda: False)

    schedule_corpus_prefetch("你好")
    assert mod.prefetch_queue().qsize() == 0

    schedule_corpus_prefetch("你好")
    assert mod.prefetch_queue().qsize() == 1


@pytest.mark.asyncio
async def test_schedule_prefetch_long_keyword_enqueues_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "prefetch")
    monkeypatch.setattr(mod, "should_skip_corpus_prefetch", lambda: False)

    schedule_corpus_prefetch("这是一个更长的话题")

    assert mod.prefetch_queue().qsize() == 1


@pytest.mark.asyncio
async def test_prefetch_consumer_keeps_keyword_deduped_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "prefetch")
    keywords = "这是一个更长的话题"

    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_execute(keywords: str) -> None:
        assert keywords == "这是一个更长的话题"
        started.set()
        await release.wait()

    monkeypatch.setattr(mod, "execute_corpus_prefetch", fake_execute)

    task = asyncio.create_task(mod.run_prefetch_consumer())
    try:
        schedule_corpus_prefetch(keywords)
        await started.wait()

        schedule_corpus_prefetch(keywords)

        assert mod.prefetch_queue().qsize() == 0
    finally:
        release.set()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        mod.clear_corpus_prefetch_runtime_state()


@pytest.mark.asyncio
async def test_prefetch_recently_finished_keyword_enters_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.features.corpus import prefetch as mod

    mod.clear_corpus_prefetch_runtime_state()
    monkeypatch.setattr(mod, "remote_corpus_find_mode", lambda: "prefetch")
    keywords = "这是一个更长的话题"

    async def fake_execute(keywords: str) -> None:
        assert keywords == "这是一个更长的话题"

    monkeypatch.setattr(mod, "execute_corpus_prefetch", fake_execute)

    task = asyncio.create_task(mod.run_prefetch_consumer())
    try:
        schedule_corpus_prefetch(keywords)
        await asyncio.wait_for(mod.prefetch_queue().join(), timeout=1.0)

        schedule_corpus_prefetch(keywords)

        assert mod.prefetch_queue().qsize() == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        mod.clear_corpus_prefetch_runtime_state()


@pytest.mark.asyncio
async def test_import_remote_context_inserts_when_missing() -> None:
    local = AsyncMock()
    local.context_exists_by_keywords = AsyncMock(return_value=False)
    local.insert = AsyncMock()
    ctx = Context.model_construct(
        keywords="kw",
        time=1,
        trigger_count=1,
        answers=[Answer(keywords="a", group_id=1, count=1, time=1, messages=["hi"])],
        ban=[],
        clear_time=0,
    )
    with patch("src.features.corpus.prefetch.invalidate_find_cache", new_callable=AsyncMock) as inv:
        ok = await import_remote_context_to_local(local, ctx)
    assert ok is True
    local.insert.assert_awaited_once()
    inv.assert_awaited_once_with("kw")


def test_prefetch_concurrency_keeps_background_single_worker_on_small_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.foundation.db.pool_budget.remote_corpus_concurrency_limit", lambda: 3)
    monkeypatch.setattr("src.foundation.db.pool_budget.cap_by_pg_pool", lambda requested, workload_fraction=0.3: 1)

    assert prefetch_concurrency() == 1
