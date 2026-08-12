"""LLM 产品共用的 ``httpx.AsyncClient``：复用连接池，避免每请求重建。"""

from __future__ import annotations

import asyncio

import httpx

_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


async def get_llm_shared_httpx_client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    async with _lock:
        if _client is None or _client.is_closed or _client_loop is not loop:
            if _client is not None and not _client.is_closed:
                await _client.aclose()
            _client = httpx.AsyncClient(timeout=None, trust_env=True)
            _client_loop = loop
        return _client
