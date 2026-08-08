from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.core.platform.message_runtime.models import MessageContext


def _context(*, is_to_me: bool = False) -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="闲聊",
        raw_text="闲聊",
        is_to_me=is_to_me,
        command_traffic=False,
        route_modules=frozenset(),
    )


@pytest.mark.asyncio
async def test_repeater_native_handler_runs_existing_business_path_and_continues_legacy(monkeypatch) -> None:
    from packages.repeater import message_runtime_handler as module

    legacy_handler = AsyncMock()
    monkeypatch.setattr(module, "handle_group_message", legacy_handler)
    handler = module.RepeaterNativeHandler()

    outcome = await handler.handle(_context(), bot="bot", event="event")

    legacy_handler.assert_awaited_once_with("bot", "event")
    assert outcome.handled is True
    assert outcome.continue_legacy is True
    assert outcome.legacy_exclude_modules == frozenset({"repeater"})


def test_repeater_native_handler_does_not_compete_with_direct_llm_chat() -> None:
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    assert RepeaterNativeHandler().accepts(_context(is_to_me=True)) is False
