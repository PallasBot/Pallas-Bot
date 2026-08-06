from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.llm_chat import status_commands


@pytest.mark.asyncio
async def test_sticker_test_sends_cached_repeater_image_without_text_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    send_image = AsyncMock(return_value=True)
    monkeypatch.setattr(status_commands, "send_cached_sticker_image", send_image, raising=False)
    bot = MagicMock()
    event = SimpleNamespace(group_id=222, user_id=333, get_plaintext=lambda: "牛牛测试表情")

    result = await status_commands.run_sticker_test(bot, event)

    assert result is None
    send_image.assert_awaited_once_with(bot, 222)


@pytest.mark.asyncio
async def test_sticker_test_reports_when_no_cached_image_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_commands, "send_cached_sticker_image", AsyncMock(return_value=False), raising=False)
    bot = MagicMock()
    event = SimpleNamespace(group_id=222, user_id=333, get_plaintext=lambda: "牛牛测试表情")

    result = await status_commands.run_sticker_test(bot, event)

    assert result == "没有可发送的 Repeater 缓存表情图。"


@pytest.mark.asyncio
async def test_llm_sticker_test_uses_the_text_after_command(monkeypatch: pytest.MonkeyPatch) -> None:
    enqueue = AsyncMock(return_value="job")
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_recent_images",
        AsyncMock(return_value=[("a", b"a"), ("b", b"b"), ("c", b"c")]),
    )
    monkeypatch.setattr("pallas.product.llm.sticker_vision.enqueue_sticker_vision_job", enqueue)
    monkeypatch.setattr(status_commands, "get_llm_config", lambda: SimpleNamespace(llm_sticker_vision_timeout_sec=17.0))
    bot = MagicMock()
    bot.self_id = 111
    event = SimpleNamespace(group_id=222, user_id=333, message_id=444, get_plaintext=lambda: "牛牛测试LLM表情 太好笑了")

    result = await status_commands.run_llm_sticker_test(bot, event)

    assert result is None
    assert enqueue.await_args.kwargs["user_text"] == "太好笑了"
    assert enqueue.await_args.kwargs["timeout_sec"] == 17.0


def test_llm_sticker_test_does_not_block_llm_chat() -> None:
    assert status_commands.llm_sticker_test_cmd.block is False


@pytest.mark.asyncio
async def test_llm_sticker_test_requires_matching_text() -> None:
    bot = MagicMock()
    event = SimpleNamespace(group_id=222, user_id=333, get_plaintext=lambda: "牛牛测试LLM表情")

    assert await status_commands.run_llm_sticker_test(bot, event) == "请在命令后附上待匹配的文本。"
