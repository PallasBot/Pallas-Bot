from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from packages.repeater import bundle_lookup as mod


@pytest.mark.asyncio
async def test_find_reply_bundle_bounded_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import bundle_cache

    bundle_cache.clear_repeater_bundle_cache_for_tests()
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 0.01)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_cache_ttl_sec", lambda: 0.0)

    class SlowChat:
        chat_data = type("D", (), {"bot_id": 1, "group_id": 2, "raw_message": "x", "keywords": "x"})()

        async def find_reply_bundle(self):
            await asyncio.sleep(1.0)
            return object()

    assert await mod.find_reply_bundle_bounded(SlowChat()) is None


@pytest.mark.asyncio
async def test_find_reply_bundle_bounded_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import bundle_cache

    bundle_cache.clear_repeater_bundle_cache_for_tests()
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 1.0)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_cache_ttl_sec", lambda: 5.0)
    sentinel = object()
    calls = {"n": 0}

    class Chat:
        chat_data = type("D", (), {"bot_id": 1, "group_id": 2, "raw_message": "hi", "keywords": "hi"})()

        async def find_reply_bundle(self):
            calls["n"] += 1
            return sentinel

    chat = Chat()
    assert await mod.find_reply_bundle_bounded(chat) is sentinel
    assert await mod.find_reply_bundle_bounded(chat) is sentinel
    assert calls["n"] == 1
