from __future__ import annotations

import asyncio

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.governance import (
    clear_llm_chat_governance_state,
    is_llm_chat_group_allowed,
    llm_chat_concurrency_limit,
    parse_group_id_set,
    release_llm_chat_slot,
    try_acquire_llm_chat_slot,
)


@pytest.fixture(autouse=True)
def reset_governance() -> None:
    clear_llm_chat_governance_state()
    yield
    clear_llm_chat_governance_state()


@pytest.fixture
def queue_cfg(monkeypatch: pytest.MonkeyPatch) -> LlmConfig:
    import pallas.product.llm.governance as gov

    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(gov, "llm_chat_sem", lambda: semaphore)
    return LlmConfig(
        llm_governance_enabled=True,
        llm_chat_max_concurrency=1,
        llm_chat_queue_enabled=True,
        llm_chat_queue_max=2,
        llm_chat_queue_wait_sec=0.5,
    )


def test_parse_group_id_set_csv_and_json() -> None:
    assert parse_group_id_set("100,200") == {100, 200}
    assert parse_group_id_set("[300, 400]") == {300, 400}


def test_group_allowlist_respects_disabled_ids() -> None:
    cfg = LlmConfig(llm_chat_disabled_group_ids=[12345])
    assert is_llm_chat_group_allowed(12345, cfg=cfg) is False
    assert is_llm_chat_group_allowed(99999, cfg=cfg) is True


def test_concurrency_respects_configured_limit() -> None:
    cfg = LlmConfig(llm_chat_max_concurrency=2)
    assert llm_chat_concurrency_limit(cfg) <= 2


@pytest.mark.asyncio
async def test_check_llm_chat_gate_disabled_by_default() -> None:
    clear_llm_config_cache()
    from pallas.product.llm.governance import check_llm_chat_gate

    assert await check_llm_chat_gate(object(), 10001) is None


@pytest.mark.asyncio
async def test_queue_wait_grants_slot_when_released(queue_cfg: LlmConfig) -> None:
    first = await try_acquire_llm_chat_slot(queue=False, cfg=queue_cfg)
    assert first is not None
    assert first.acquired

    pending = asyncio.create_task(try_acquire_llm_chat_slot(queue=True, cfg=queue_cfg))
    await asyncio.sleep(0.05)
    assert not pending.done()
    release_llm_chat_slot(first)

    waiting = await pending
    assert waiting is not None
    assert waiting.acquired
    release_llm_chat_slot(waiting)


@pytest.mark.asyncio
async def test_non_queue_priority_still_skipped_when_busy(queue_cfg: LlmConfig) -> None:
    import pallas.product.llm.governance as gov

    first = await try_acquire_llm_chat_slot(queue=False, cfg=queue_cfg)
    assert first is not None
    assert first.acquired
    before = gov._skipped_busy

    skipped = await try_acquire_llm_chat_slot(queue=False, cfg=queue_cfg)
    assert skipped is None
    assert gov._skipped_busy == before + 1
    release_llm_chat_slot(first)


@pytest.mark.asyncio
async def test_queue_drops_oldest_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    import pallas.product.llm.governance as gov

    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(gov, "llm_chat_sem", lambda: semaphore)
    cfg = LlmConfig(
        llm_governance_enabled=True,
        llm_chat_max_concurrency=1,
        llm_chat_queue_enabled=True,
        llm_chat_queue_max=1,
        llm_chat_queue_wait_sec=5.0,
    )

    first = await try_acquire_llm_chat_slot(queue=False, cfg=cfg)
    assert first is not None
    assert first.acquired

    await asyncio.gather(
        try_acquire_llm_chat_slot(queue=True, cfg=cfg),
        try_acquire_llm_chat_slot(queue=True, cfg=cfg),
    )
    assert gov._queue_dropped == 1

    release_llm_chat_slot(first)


@pytest.mark.asyncio
async def test_queue_timeout_returns_none(queue_cfg: LlmConfig) -> None:
    import pallas.product.llm.governance as gov

    first = await try_acquire_llm_chat_slot(queue=False, cfg=queue_cfg)
    assert first is not None
    assert first.acquired
    before = gov._queue_timeouts

    result = await try_acquire_llm_chat_slot(queue=True, cfg=queue_cfg)
    assert result is None
    assert gov._queue_timeouts == before + 1
    release_llm_chat_slot(first)
