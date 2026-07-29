from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from packages.repeater import bundle_lookup as mod


@pytest.mark.asyncio
async def test_find_reply_bundle_bounded_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 0.01)

    class SlowChat:
        chat_data = type("D", (), {"bot_id": 1, "group_id": 2})()

        async def find_reply_bundle(self):
            await asyncio.sleep(1.0)
            return object()

    assert await mod.find_reply_bundle_bounded(SlowChat()) is None


@pytest.mark.asyncio
async def test_find_reply_bundle_bounded_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 1.0)
    sentinel = object()
    chat = AsyncMock()
    chat.chat_data = type("D", (), {"bot_id": 1, "group_id": 2})()
    chat.find_reply_bundle = AsyncMock(return_value=sentinel)
    assert await mod.find_reply_bundle_bounded(chat) is sentinel
