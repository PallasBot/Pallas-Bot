from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.polish_lite import submit_corpus_assist_stages
from pallas.product.llm.repeater_capabilities import RepeaterCapabilities


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

    async def fake_polish(*args, **kwargs) -> bool:
        calls.append(f"polish:{kwargs.get('intensity', 'normal')}")
        return False

    async def fake_lite(*args, **kwargs) -> bool:
        calls.append("lite")
        return False

    monkeypatch.setattr(
        "pallas.product.llm.polish_lite.get_llm_config",
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
    monkeypatch.setattr(
        "pallas.product.llm.polish.maybe_submit_repeater_llm_polish",
        AsyncMock(side_effect=fake_polish),
    )
    monkeypatch.setattr(
        "pallas.product.llm.polish_lite.maybe_submit_repeater_llm_polish_lite",
        AsyncMock(side_effect=fake_lite),
    )
    return calls


@pytest.mark.asyncio
async def test_strong_pipeline_attempts_select_before_lite_rewrite(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pipeline_mocks(monkeypatch)

    submitted = await submit_corpus_assist_stages(
        FakeEvent(),
        user_text="接一下这句",
        candidates=["候选一", "候选二"],
        candidate_text="候选一",
        scene_tier="strong",
    )

    assert submitted is False
    assert calls == ["select", "lite"]


@pytest.mark.asyncio
async def test_weak_pipeline_attempts_lite_rewrite_before_select(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pipeline_mocks(monkeypatch)

    submitted = await submit_corpus_assist_stages(
        FakeEvent(),
        user_text="接一下这句",
        candidates=["候选一", "候选二"],
        candidate_text="候选一",
        scene_tier="weak",
    )

    assert submitted is False
    assert calls == ["lite", "select"]


@pytest.mark.asyncio
async def test_direct_chat_assist_skips_repeater_only_polish(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pipeline_mocks(monkeypatch)

    submitted = await submit_corpus_assist_stages(
        FakeEvent(),
        user_text="接一下这句",
        candidates=["候选一", "候选二"],
        candidate_text="候选一",
        scene_tier="weak",
        profile="direct_chat",
    )

    assert submitted is False
    assert calls == ["lite", "select"]


@pytest.mark.asyncio
async def test_corpus_assist_uses_supplied_capability_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_pipeline_mocks(monkeypatch)

    submitted = await submit_corpus_assist_stages(
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

    assert submitted is False
    assert calls == []
