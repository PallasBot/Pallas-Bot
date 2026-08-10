from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_run_change_name_skips_group_when_plugin_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.take_name import handlers
    from pallas.core.foundation.db import Message

    bot_id = 10001
    group_id = 20001
    target = Message.model_construct(
        group_id=group_id,
        user_id=30001,
        bot_id=bot_id,
        raw_message="test",
        plain_text="test",
        keywords="test",
        time=1,
    )
    bot = MagicMock()
    bot.call_api = AsyncMock()
    plugin_disabled = AsyncMock(return_value=True)

    monkeypatch.setattr(
        handlers.MessageStore,
        "get_random_message_from_each_group",
        AsyncMock(return_value={group_id: target}),
    )
    monkeypatch.setattr(handlers.random, "random", lambda: 0.0)
    monkeypatch.setattr(handlers, "get_bots", lambda: {str(bot_id): bot})
    monkeypatch.setattr("packages.help.plugin_manager.is_plugin_disabled", plugin_disabled)

    await handlers.run_change_name()

    plugin_disabled.assert_awaited_once_with("take_name", group_id, bot_id)
    bot.call_api.assert_not_awaited()
