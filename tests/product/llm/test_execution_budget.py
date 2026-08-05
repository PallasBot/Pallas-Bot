from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.execution_budget import (
    clear_llm_execution_budget_state,
    release_llm_execution_slot,
    try_acquire_llm_execution_slot,
)


@pytest.mark.asyncio
async def test_shared_budget_reserves_capacity_for_interactive_priority() -> None:
    clear_llm_execution_budget_state()
    cfg = LlmConfig(llm_governance_enabled=True, llm_shared_max_concurrency=4)

    weak_first = await try_acquire_llm_execution_slot("repeater_weak", cfg=cfg)
    weak_second = await try_acquire_llm_execution_slot("repeater_weak", cfg=cfg)
    strong = await try_acquire_llm_execution_slot("repeater_strong", cfg=cfg)
    ambient = await try_acquire_llm_execution_slot("ambient", cfg=cfg)

    assert weak_first is not None
    assert weak_second is None
    assert strong is not None
    assert ambient is not None

    explicit = await try_acquire_llm_execution_slot("explicit", cfg=cfg)
    assert explicit is not None

    for slot in (weak_first, strong, ambient, explicit):
        release_llm_execution_slot(slot, cfg=cfg)


@pytest.mark.asyncio
async def test_shared_budget_is_silent_when_full() -> None:
    clear_llm_execution_budget_state()
    cfg = LlmConfig(llm_governance_enabled=True, llm_shared_max_concurrency=1)

    first = await try_acquire_llm_execution_slot("explicit", cfg=cfg)
    assert first is not None
    assert await try_acquire_llm_execution_slot("explicit", cfg=cfg) is None
    release_llm_execution_slot(first, cfg=cfg)
