from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.product.llm.fallback import maybe_submit_repeater_llm_fallback
from pallas.product.llm.polish import maybe_submit_repeater_llm_polish


def _group_event(*, to_me: bool) -> MagicMock:
    event = MagicMock()
    event.is_tome.return_value = to_me
    event.group_id = 100
    event.user_id = 200
    event.self_id = 300
    return event


@pytest.mark.asyncio
async def test_repeater_fallback_skips_to_me() -> None:
    event = _group_event(to_me=True)
    assert await maybe_submit_repeater_llm_fallback(event, user_text="你好") is False


@pytest.mark.asyncio
async def test_repeater_polish_skips_to_me() -> None:
    event = _group_event(to_me=True)
    assert await maybe_submit_repeater_llm_polish(event, candidate_text="你好呀") is False


@pytest.mark.asyncio
async def test_repeater_fallback_still_runs_for_normal_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import config as llm_config_mod

    cfg = llm_config_mod.LlmConfig(llm_fallback_enabled=True, llm_chat_enabled=True, use_unified_chat_api=True)
    monkeypatch.setattr("pallas.product.llm.fallback.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "pallas.product.llm.fallback.build_fallback_system_prompt",
        AsyncMock(return_value=("system", None, None, {})),
    )
    monkeypatch.setattr(
        "pallas.product.llm.fallback.build_fallback_expression_suffix",
        AsyncMock(return_value="【表达习惯参考】群里常接这些说法/梗：牛牛税。"),
    )
    monkeypatch.setattr("pallas.product.llm.fallback.TaskManager.add_task", AsyncMock())
    submit_mock = AsyncMock(return_value=MagicMock(ok=True, task_id="task-1"))
    monkeypatch.setattr("pallas.product.llm.fallback.submit_chat_task", submit_mock)

    event = _group_event(to_me=False)
    assert await maybe_submit_repeater_llm_fallback(event, user_text="你好") is True
    req = submit_mock.await_args.args[0]
    assert "表达习惯参考" in req.user_text
