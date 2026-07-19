from __future__ import annotations

import pytest
from sqlalchemy.exc import TimeoutError as SATimeoutError

from pallas.product.corpus import find_cache as mod


@pytest.mark.asyncio
async def test_reply_find_cache_backoff_after_pool_timeout() -> None:
    await mod.reset_find_cache_for_tests()
    calls = 0

    async def loader(keywords: str):
        nonlocal calls
        calls += 1
        raise SATimeoutError("QueuePool limit", None, None)

    first = await mod.cached_find_by_keywords_for_reply("hello", loader)
    second = await mod.cached_find_by_keywords_for_reply("hello", loader)

    assert first is None
    assert second is None
    assert calls == 1
