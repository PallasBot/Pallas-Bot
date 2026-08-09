from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.message_runtime.models import MessageContext


def context(*, raw_text: str = "牛牛") -> MessageContext:
    return MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=raw_text,
        raw_text=raw_text,
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"greeting"}),
    )


@pytest.mark.asyncio
async def test_call_me_native_handler_returns_the_selected_voice(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from packages.greeting.native import CallMeNativeHandler

    voice_path = tmp_path / "voice.mp3"
    voice_path.write_bytes(b"voice")
    cooldown = MagicMock()
    cooldown.is_cooldown = AsyncMock(return_value=True)
    cooldown.refresh_cooldown = AsyncMock()
    event = MagicMock(user_id=3)
    monkeypatch.setattr("packages.greeting.native.duel_qte_blocks_greeting_user", lambda *_args: False)
    monkeypatch.setattr("packages.greeting.native.greeting_plugin_disabled", AsyncMock(return_value=False))
    monkeypatch.setattr("packages.greeting.native.BotConfig", lambda *_args: cooldown)
    monkeypatch.setattr("packages.greeting.native.get_random_voice", lambda *_args: voice_path)
    monkeypatch.setattr("packages.greeting.native.asyncio.to_thread", AsyncMock(return_value=b"voice"))

    outcome = await CallMeNativeHandler().handle(context(), bot=MagicMock(), event=event)

    assert outcome.handled is True
    assert len(outcome.actions) == 1
    assert outcome.actions[0].message.type == "record"
    assert outcome.actions[0].message.data["file"] == "base64://dm9pY2U="
    cooldown.refresh_cooldown.assert_awaited_once_with("call_me")


@pytest.mark.asyncio
async def test_call_me_native_handler_falls_back_for_non_exact_text() -> None:
    from packages.greeting.native import CallMeNativeHandler

    outcome = await CallMeNativeHandler().handle(context(raw_text="牛牛！"), bot=MagicMock(), event=MagicMock())

    assert outcome.fallback_to_legacy is True


def test_call_me_native_handler_is_the_exact_passive_primary() -> None:
    from packages.greeting.native import CallMeNativeHandler
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler
    from pallas.core.platform.message_runtime.handlers import NativeHandlerRegistry
    from pallas.core.platform.message_runtime.planner import MessagePlanner

    registry = NativeHandlerRegistry()
    registry.register(CallMeNativeHandler())
    registry.register(RepeaterNativeHandler())

    plan = MessagePlanner(registry).plan(
        MessageContext(
            ingress_id="1:2:3",
            bot_id=1,
            group_id=2,
            message_id=3,
            plain_text="牛牛",
            raw_text="牛牛",
            is_to_me=False,
            command_traffic=False,
            route_modules=frozenset({"greeting"}),
        )
    )

    assert plan.handler_ids == ("greeting.call_me",)
    assert plan.reason == "unique_exact_passive"
