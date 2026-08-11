from __future__ import annotations

import asyncio

import pytest

from packages.pb_webui.console_read_cache import cached_read, clear_extended_read_cache


@pytest.mark.asyncio
async def test_cached_read_starts_ttl_after_slow_loader_completes() -> None:
    clear_extended_read_cache()
    calls = 0

    async def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.06)
        return {"calls": calls}

    try:
        assert await cached_read(key="slow-loader", loader=loader, ttl_sec=0.05) == {"calls": 1}
        assert await cached_read(key="slow-loader", loader=loader, ttl_sec=0.05) == {"calls": 1}
        assert calls == 1
    finally:
        clear_extended_read_cache()
