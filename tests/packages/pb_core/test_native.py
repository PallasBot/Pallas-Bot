from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.message_runtime.models import MessageContext, SendAction


def context(*, plain_text: str = "#pallas") -> MessageContext:
    return MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=plain_text,
        raw_text=plain_text,
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"pb_core"}),
    )


@pytest.mark.asyncio
async def test_status_native_handler_sends_the_existing_status_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.pb_core.native import StatusNativeHandler

    handler = StatusNativeHandler()
    bot = MagicMock()
    event = MagicMock()
    monkeypatch.setattr("packages.pb_core.native.satisfies_command_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.pb_core.native.is_command_cooldown_ready", AsyncMock(return_value=True))
    refresh = AsyncMock()
    monkeypatch.setattr("packages.pb_core.native.refresh_command_cooldown", refresh)
    monkeypatch.setattr("packages.pb_core.native.format_runtime_status_text", lambda **_kwargs: "status")

    outcome = await handler.handle(context(), bot=bot, event=event)

    assert outcome.handled is True
    assert outcome.actions == (SendAction(message="status"),)
    refresh.assert_awaited_once_with(event, "pb_core.status", default_cd_sec=10)


@pytest.mark.asyncio
async def test_status_native_handler_falls_back_when_command_is_not_exact() -> None:
    from packages.pb_core.native import StatusNativeHandler

    outcome = await StatusNativeHandler().handle(
        context(plain_text="#pallas details"), bot=MagicMock(), event=MagicMock()
    )

    assert outcome.fallback_to_legacy is True
