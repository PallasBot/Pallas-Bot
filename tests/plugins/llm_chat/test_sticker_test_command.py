from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.llm_chat import status_commands


@pytest.mark.asyncio
async def test_sticker_test_sends_cached_repeater_image(monkeypatch: pytest.MonkeyPatch) -> None:
    send_image = AsyncMock(return_value=True)
    monkeypatch.setattr(status_commands, "send_cached_sticker_image", send_image, raising=False)
    bot = MagicMock()
    event = SimpleNamespace(group_id=222, user_id=333, get_plaintext=lambda: "牛牛测试表情")

    result = await status_commands.run_sticker_test(bot, event)

    assert result == "已发送一张 Repeater 缓存表情图。"
    send_image.assert_awaited_once_with(bot, 222)


@pytest.mark.asyncio
async def test_sticker_test_reports_when_no_cached_image_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_commands, "send_cached_sticker_image", AsyncMock(return_value=False), raising=False)
    bot = MagicMock()
    event = SimpleNamespace(group_id=222, user_id=333, get_plaintext=lambda: "牛牛测试表情")

    result = await status_commands.run_sticker_test(bot, event)

    assert result == "没有可发送的 Repeater 缓存表情图。"
