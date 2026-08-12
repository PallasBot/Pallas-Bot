from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.llm_chat import style_commands


@pytest.mark.asyncio
async def test_reset_group_style_clears_bot_group_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared: dict[tuple[int, int], dict] = {}

    def fake_clear(**kwargs) -> dict:
        cleared[(kwargs["bot_id"], kwargs["group_id"])] = kwargs
        return {"example_count": 7}

    monkeypatch.setattr(style_commands, "clear_semantic_style_data", fake_clear)
    bot = MagicMock()
    bot.self_id = 111
    matcher = AsyncMock()
    ctx = SimpleNamespace(bot=bot, group_id=222, matcher=matcher)

    await style_commands.handle_reset_group_style(ctx)

    assert cleared == {(111, 222): {"bot_id": 111, "group_id": 222}}
    matcher.send.assert_awaited_once()
    assert "7" in str(matcher.send.await_args.args[0])


@pytest.mark.asyncio
async def test_reset_group_style_skips_without_group(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_clear(**kwargs) -> dict:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(style_commands, "clear_semantic_style_data", fake_clear)
    bot = MagicMock()
    bot.self_id = 111
    matcher = AsyncMock()
    ctx = SimpleNamespace(bot=bot, group_id=None, matcher=matcher)

    await style_commands.handle_reset_group_style(ctx)

    assert called is False
    matcher.send.assert_not_awaited()


def test_reset_style_command_defaults_to_group_moderator() -> None:
    from packages.llm_chat import __plugin_meta__

    rows = __plugin_meta__.extra["command_permissions"]
    row = next(item for item in rows if item["id"] == "llm_chat.reset_style")
    assert row["default"] == "group_moderator"
