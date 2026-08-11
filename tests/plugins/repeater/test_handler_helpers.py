from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment


@pytest.mark.asyncio
async def test_post_proc_drops_image_when_persistent_cache_misses(monkeypatch) -> None:
    from packages.repeater.handlers import helpers

    async def cache_miss(_cq_code):
        return None

    monkeypatch.setattr(helpers, "get_image", cache_miss)
    monkeypatch.setattr(helpers.Chat, "reply_post_proc", AsyncMock(return_value=True))

    message = Message(MessageSegment.image("https://example.invalid/expired.jpg"))

    assert await helpers.post_proc(message, 111, 222) == Message()
