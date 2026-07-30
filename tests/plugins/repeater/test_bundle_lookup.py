from __future__ import annotations

import asyncio

import pytest

from packages.repeater import bundle_lookup as mod


@pytest.mark.asyncio
async def test_find_reply_bundle_bounded_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import bundle_cache

    bundle_cache.clear_repeater_bundle_cache_for_tests()
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 0.01)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_cache_ttl_sec", lambda: 0.0)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_negative_cache_ttl_sec", lambda: 0.0)

    class SlowChat:
        chat_data = type("D", (), {"bot_id": 1, "group_id": 2, "raw_message": "x", "keywords": "x"})()

        async def find_reply_bundle(self):
            await asyncio.sleep(1.0)
            return object()

    assert await mod.find_reply_bundle_bounded(SlowChat()) is None


@pytest.mark.asyncio
async def test_find_reply_bundle_bounded_uses_positive_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import bundle_cache

    bundle_cache.clear_repeater_bundle_cache_for_tests()
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 1.0)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_cache_ttl_sec", lambda: 5.0)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_negative_cache_ttl_sec", lambda: 5.0)
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


@pytest.mark.asyncio
async def test_find_reply_bundle_negative_cache_shared_across_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import bundle_cache

    bundle_cache.clear_repeater_bundle_cache_for_tests()
    monkeypatch.setattr(mod, "repeater_bundle_timeout_sec", lambda: 1.0)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_cache_ttl_sec", lambda: 5.0)
    monkeypatch.setattr(bundle_cache, "repeater_bundle_negative_cache_ttl_sec", lambda: 30.0)
    calls = {"n": 0}

    class Chat:
        def __init__(self, bot_id: int) -> None:
            self.chat_data = type(
                "D",
                (),
                {"bot_id": bot_id, "group_id": 99, "raw_message": "无人接话", "keywords": "无人 接话"},
            )()

        async def find_reply_bundle(self):
            calls["n"] += 1
            return None

    assert await mod.find_reply_bundle_bounded(Chat(1)) is None
    assert await mod.find_reply_bundle_bounded(Chat(2)) is None
    assert await mod.find_reply_bundle_bounded(Chat(3)) is None
    assert calls["n"] == 1
