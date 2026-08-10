from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.core.platform.message_runtime.models import MessageContext


def _context() -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="你好",
        raw_text="你好",
        is_to_me=True,
        command_traffic=False,
        route_modules=frozenset(),
    )


@pytest.mark.asyncio
async def test_native_llm_handler_collects_direct_reply_without_matcher_send(monkeypatch) -> None:
    from packages.llm_chat import message_runtime_handler as module

    async def legacy_handler(_bot, _event, *, send_message) -> None:
        await send_message("reply")

    legacy_handler = AsyncMock(side_effect=legacy_handler)
    monkeypatch.setattr(module, "handle_llm_chat", legacy_handler)

    outcome = await module.LlmChatDirectHandler().handle(_context(), bot="bot", event="event")

    legacy_handler.assert_awaited_once()
    assert [action.message for action in outcome.actions] == ["reply"]
