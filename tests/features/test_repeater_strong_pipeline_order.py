from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.repeater_capabilities import RepeaterCapabilities
from pallas.product.llm.select import submit_repeater_corpus_select


class FakeEvent:
    self_id = 10001
    group_id = 123
    user_id = 456
    message_id = 789


def install_pipeline_mocks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def fake_select(*args, **kwargs) -> bool:
        calls.append("select")
        return False

    monkeypatch.setattr(
        "pallas.product.llm.select.get_llm_config",
        lambda: LlmConfig(
            llm_chat_enabled=True,
            llm_select_enabled=True,
            llm_polish_enabled=True,
            llm_polish_lite_enabled=True,
            llm_polish_lite_sample_rate=1.0,
        ),
    )
    monkeypatch.setattr(
        "packages.repeater.opportunity_gate.looks_like_reply_cue",
        lambda user_text: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.select.maybe_submit_repeater_llm_select",
        AsyncMock(side_effect=fake_select),
    )
    return calls


@pytest.mark.asyncio
async def test_corpus_assist_only_attempts_select(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pipeline_mocks(monkeypatch)

    submitted = await submit_repeater_corpus_select(
        FakeEvent(),
        user_text="接一下这句",
        candidates=["候选一", "候选二"],
        candidate_text="候选一",
        scene_tier="strong",
    )

    assert submitted is False
    assert calls == ["select"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_corpus_assist_uses_supplied_capability_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pipeline_mocks(monkeypatch)

    submitted = await submit_repeater_corpus_select(
        FakeEvent(),
        user_text="接一下这句",
        candidates=["候选一", "候选二"],
        candidate_text="候选一",
        capabilities=RepeaterCapabilities(
            mode="off",
            llm_enabled=True,
            fallback_enabled=False,
            polish_enabled=False,
            select_enabled=False,
            polish_lite_enabled=False,
        ),
    )

    assert submitted is None
    assert calls == []
