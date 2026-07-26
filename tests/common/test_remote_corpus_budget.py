import asyncio

import pytest

from pallas.product.corpus.remote_budget import (
    RemoteCorpusBudget,
    clear_remote_corpus_budget_state,
    drain_remote_corpus_skip_counters,
    should_skip_remote_corpus,
)


@pytest.mark.asyncio
async def test_remote_corpus_budget_skips_under_pressure(monkeypatch):
    clear_remote_corpus_budget_state()
    monkeypatch.setattr(
        "pallas.product.corpus.remote_budget.pg_pool_under_pressure",
        lambda threshold=0.75: True,
    )
    assert should_skip_remote_corpus(hot_path=True) is True
    async with RemoteCorpusBudget(hot_path=True) as budget:
        assert budget.skipped is True


@pytest.mark.asyncio
async def test_remote_corpus_budget_acquires_when_healthy(monkeypatch):
    clear_remote_corpus_budget_state()
    monkeypatch.setattr(
        "pallas.product.corpus.remote_budget.pg_pool_under_pressure",
        lambda threshold=0.75: False,
    )
    monkeypatch.setattr(
        "pallas.product.corpus.remote_budget.remote_corpus_concurrency_limit",
        lambda: 2,
    )
    async with RemoteCorpusBudget(hot_path=False, wait=True) as budget:
        assert budget.skipped is False


def test_remote_corpus_background_threshold_more_conservative(monkeypatch):
    clear_remote_corpus_budget_state()
    seen: list[float] = []

    def fake_under_pressure(*, threshold: float = 0.75) -> bool:
        seen.append(threshold)
        return False

    monkeypatch.setattr("pallas.product.corpus.remote_budget.pg_pool_under_pressure", fake_under_pressure)

    assert should_skip_remote_corpus(hot_path=False) is False
    assert seen == [0.55]


def _open_remote_budget(monkeypatch, *, limit: int = 1) -> None:
    clear_remote_corpus_budget_state()
    monkeypatch.setattr(
        "pallas.product.corpus.remote_budget.pg_pool_under_pressure",
        lambda *, threshold=0.75: False,
    )
    monkeypatch.setattr(
        "pallas.product.corpus.remote_budget.remote_corpus_concurrency_limit",
        lambda: limit,
    )


@pytest.mark.asyncio
async def test_remote_corpus_budget_wait_false_acquires_when_free(monkeypatch):
    _open_remote_budget(monkeypatch, limit=1)
    async with RemoteCorpusBudget(hot_path=True, wait=False) as budget:
        assert budget.skipped is False


@pytest.mark.asyncio
async def test_remote_corpus_budget_wait_false_skips_when_busy(monkeypatch):
    _open_remote_budget(monkeypatch, limit=1)
    drain_remote_corpus_skip_counters()
    async with RemoteCorpusBudget(hot_path=True, wait=False) as holder:
        assert holder.skipped is False
        async with RemoteCorpusBudget(hot_path=False, wait=False) as busy:
            assert busy.skipped is True
    snap = drain_remote_corpus_skip_counters()
    assert snap["skipped_busy"] >= 1


@pytest.mark.asyncio
async def test_remote_corpus_budget_wait_true_queues_when_busy(monkeypatch):
    _open_remote_budget(monkeypatch, limit=1)
    held = asyncio.Event()

    async def hold_then_release() -> None:
        async with RemoteCorpusBudget(hot_path=True, wait=False) as holder:
            assert holder.skipped is False
            held.set()
            await asyncio.sleep(0.05)

    holder_task = asyncio.create_task(hold_then_release())
    await asyncio.wait_for(held.wait(), timeout=1.0)
    async with RemoteCorpusBudget(hot_path=False, wait=True) as waiter:
        assert waiter.skipped is False
    await holder_task
