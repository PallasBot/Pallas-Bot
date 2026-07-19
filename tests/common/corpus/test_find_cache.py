from __future__ import annotations

import asyncio

import pytest

from pallas.product.corpus.find_cache import (
    cached_find_by_keywords,
    cached_find_by_keywords_for_reply,
    reset_find_cache_for_tests,
)


@pytest.mark.asyncio
async def test_find_cache_hits_without_second_loader_call():
    await reset_find_cache_for_tests()
    calls = 0

    async def loader(keywords: str):
        nonlocal calls
        calls += 1
        return {"kw": keywords} if keywords == "hello" else None

    assert await cached_find_by_keywords("hello", loader) == {"kw": "hello"}
    assert await cached_find_by_keywords("hello", loader) == {"kw": "hello"}
    assert calls == 1

    assert await cached_find_by_keywords("missing", loader) is None
    assert await cached_find_by_keywords("missing", loader) is None
    assert calls == 2


@pytest.mark.asyncio
async def test_reply_find_cache_hits_without_second_loader_call():
    await reset_find_cache_for_tests()
    calls = 0

    async def loader(keywords: str):
        nonlocal calls
        calls += 1
        return {"kw": keywords, "reply": True} if keywords == "hello" else None

    assert await cached_find_by_keywords_for_reply("hello", loader) == {"kw": "hello", "reply": True}
    assert await cached_find_by_keywords_for_reply("hello", loader) == {"kw": "hello", "reply": True}
    assert calls == 1

    assert await cached_find_by_keywords_for_reply("missing", loader) is None
    assert await cached_find_by_keywords_for_reply("missing", loader) is None
    assert calls == 2


@pytest.mark.asyncio
async def test_reply_find_cache_dedupes_concurrent_miss():
    await reset_find_cache_for_tests()
    calls = 0
    started = asyncio.Event()

    async def loader(keywords: str):
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.sleep(0.01)
        return {"kw": keywords, "reply": True}

    first = asyncio.create_task(cached_find_by_keywords_for_reply("hot", loader))
    await started.wait()
    second = asyncio.create_task(cached_find_by_keywords_for_reply("hot", loader))

    assert await first == {"kw": "hot", "reply": True}
    assert await second == {"kw": "hot", "reply": True}
    assert calls == 1
