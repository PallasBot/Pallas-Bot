"""LLM 产品共用的 ``httpx.AsyncClient``：复用连接池，避免每请求重建。"""

from __future__ import annotations

import asyncio

import httpx
from nonebot import logger

_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None

# httpcore 在代理隧道 TLS 失败 / 请求取消时会留下永不回收的 ACTIVE 连接，池满后新请求只会
# PoolTimeout（encode/httpcore#1093）；连续达到阈值即视为池已楔死，下次取用时整池重建自愈。
_pool_timeout_streak = 0
_POOL_REBUILD_STREAK = 3


def note_llm_http_pool_timeout() -> None:
    global _pool_timeout_streak
    _pool_timeout_streak += 1


def note_llm_http_success() -> None:
    global _pool_timeout_streak
    _pool_timeout_streak = 0


async def get_llm_shared_httpx_client() -> httpx.AsyncClient:
    global _client, _client_loop, _pool_timeout_streak
    loop = asyncio.get_running_loop()
    async with _lock:
        if (
            _pool_timeout_streak >= _POOL_REBUILD_STREAK
            or _client is None
            or _client.is_closed
            or _client_loop is not loop
        ):
            if _client is not None and not _client.is_closed:
                if _pool_timeout_streak >= _POOL_REBUILD_STREAK:
                    logger.warning(
                        "LLM shared httpx pool wedged after [{}] consecutive pool timeouts, rebuilding client",
                        _pool_timeout_streak,
                    )
                await _client.aclose()
            _client = httpx.AsyncClient(timeout=None, trust_env=True)
            _client_loop = loop
            _pool_timeout_streak = 0
        return _client
