from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_context_exists_gate_cache(beanie_fixture, monkeypatch):
    from packages.repeater import context_exists_cache as cache

    await cache.reset_context_exists_cache()
    calls: list[str] = []

    async def counting_fetch(keywords: str) -> bool:
        calls.append(keywords)
        return False

    monkeypatch.setattr(cache, "_fetch_exists_db", counting_fetch)

    kw = "测试关键词 gate"
    assert await cache.context_exists_for_learn(kw) is False
    assert await cache.context_exists_for_learn(kw) is False
    assert len(calls) == 1

    await cache.note_context_exists(kw)
    assert await cache.context_exists_for_learn(kw) is True
    assert len(calls) == 1

    await cache.invalidate_context_exists_cache(kw)
    assert await cache.context_exists_for_learn(kw) is False
    assert len(calls) == 2

    await cache.reset_context_exists_cache()
