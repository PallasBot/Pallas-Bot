"""message_scrub 远程审查共用的 ``httpx.AsyncClient``。"""

from __future__ import annotations

import asyncio

import httpx

_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None


async def get_scrub_async_httpx_client() -> httpx.AsyncClient:
    global _client
    async with _lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(timeout=None, trust_env=True)
        return _client
