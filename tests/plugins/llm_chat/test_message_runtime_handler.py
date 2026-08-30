from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.message_runtime.models import MessageContext


def _context(
    *,
    plain_text: str = "你好",
    command_traffic: bool = False,
    route_modules: frozenset[str] = frozenset(),
) -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=plain_text,
        raw_text=plain_text,
        is_to_me=True,
        command_traffic=command_traffic,
        route_modules=route_modules,
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


@pytest.mark.asyncio
async def test_native_llm_handler_falls_back_for_empty_direct_mention(monkeypatch) -> None:
    from packages.llm_chat import message_runtime_handler as module

    legacy_handler = AsyncMock()
    monkeypatch.setattr(module, "handle_llm_chat", legacy_handler)

    event = MagicMock(reply=None)
    event.get_message.return_value = ""
    outcome = await module.LlmChatDirectHandler().handle(_context(plain_text=""), bot="bot", event=event)

    assert outcome.fallback_to_matcher is True
    legacy_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_llm_handler_falls_back_for_command_traffic(monkeypatch) -> None:
    from packages.llm_chat import message_runtime_handler as module

    legacy_handler = AsyncMock()
    monkeypatch.setattr(module, "handle_llm_chat", legacy_handler)

    outcome = await module.LlmChatDirectHandler().handle(
        _context(plain_text="重置表达", command_traffic=True, route_modules=frozenset({"llm_chat"})),
        bot="bot",
        event="event",
    )

    assert outcome.fallback_to_matcher is True
    assert outcome.fallback_reason == "command_traffic"
    legacy_handler.assert_not_awaited()
