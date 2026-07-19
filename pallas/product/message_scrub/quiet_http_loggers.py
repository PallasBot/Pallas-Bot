from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_lock = asyncio.Lock()
_depth = 0
_saved_levels: tuple[int, int] | None = None


@asynccontextmanager
async def scrub_http_log_noise() -> AsyncIterator[None]:
    """审查出站 HTTP 期间将 ``httpx`` / ``httpcore`` 调至 WARNING，避免 DEBUG 刷屏；退出后恢复原级别。"""
    global _depth, _saved_levels
    httpx_logger = logging.getLogger("httpx")
    httpcore_logger = logging.getLogger("httpcore")
    async with _lock:
        if _depth == 0:
            _saved_levels = (httpx_logger.level, httpcore_logger.level)
            httpx_logger.setLevel(logging.WARNING)
            httpcore_logger.setLevel(logging.WARNING)
        _depth += 1
    try:
        yield
    finally:
        async with _lock:
            _depth -= 1
            if _depth == 0 and _saved_levels is not None:
                httpx_logger.setLevel(_saved_levels[0])
                httpcore_logger.setLevel(_saved_levels[1])
                _saved_levels = None
