from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.greeting import commands


def _poke_event() -> SimpleNamespace:
    return SimpleNamespace(
        notice_type="notify",
        sub_type="poke",
        self_id=10001,
        group_id=123,
        target_id=10001,
        user_id=40000,
    )


async def _run_poke(monkeypatch: pytest.MonkeyPatch, *, allow: bool) -> AsyncMock:
    config = MagicMock()
    config.is_cooldown = AsyncMock(return_value=True)
    config.refresh_cooldown = AsyncMock()
    config.allow_window_action = AsyncMock(return_value=allow)
    bot = MagicMock()
    bot.call_api = AsyncMock()
    monkeypatch.setattr(commands, "greeting_plugin_disabled", AsyncMock(return_value=False))
    monkeypatch.setattr(commands, "BotConfig", lambda *_args: config)
    monkeypatch.setattr(commands, "plugin_config", SimpleNamespace(poke_limit_max=3, poke_limit_window=60))
    monkeypatch.setattr(commands, "get_bot", lambda *_args: bot)
    monkeypatch.setattr(commands.asyncio, "sleep", AsyncMock())

    await commands.handle_notice(_poke_event())
    return bot.call_api


@pytest.mark.asyncio
async def test_poke_within_window_limit_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    call_api = await _run_poke(monkeypatch, allow=True)
    call_api.assert_awaited_once_with(
        "group_poke",
        group_id=123,
        user_id=40000,
    )


@pytest.mark.asyncio
async def test_poke_over_window_limit_skips_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    call_api = await _run_poke(monkeypatch, allow=False)
    call_api.assert_not_awaited()
