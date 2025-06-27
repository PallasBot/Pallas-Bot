import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from nonebot import get_bot, logger
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential


async def is_bot_admin(bot_id: int, group_id: int, no_cache: bool = False) -> bool:
    info = await get_bot(str(bot_id)).call_api(
        "get_group_member_info",
        **{
            "user_id": bot_id,
            "group_id": group_id,
            "no_cache": no_cache,
        },
    )
    flag: bool = info["role"] == "admin" or info["role"] == "owner"

    return flag


class HTTPXClient:
    _client: httpx.AsyncClient | None = None
    _lock = asyncio.Lock()

    DEFAULT_TIMEOUT = 10.0

    DEFAULT_RETRY = {
        "stop": stop_after_attempt(3),
        "wait": wait_exponential(multiplier=1, min=1, max=5),
        "retry": retry_if_exception_type((
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        )),
        "before_sleep": before_sleep_log(logger, logging.DEBUG),
    }

    @classmethod
    @asynccontextmanager
    async def get_client(cls):
        async with cls._lock:
            if cls._client is None or cls._client.is_closed:
                cls._client = httpx.AsyncClient(
                    timeout=cls.DEFAULT_TIMEOUT,
                )
            try:
                yield cls._client
            except httpx.TransportError as e:
                logger.error(f"httpx client transport error: {e}")
                await cls.close()
                raise
            except httpx.HTTPError as e:
                logger.warning(f"httpx client HTTP error: {e}")
                raise

    @classmethod
    async def close(cls):
        async with cls._lock:
            if cls._client and not cls._client.is_closed:
                await cls._client.aclose()
                cls._client = None

    @classmethod
    def configure_defaults(cls, timeout: float = DEFAULT_TIMEOUT, retry_config: dict[str, Any] | None = None):
        cls.DEFAULT_TIMEOUT = timeout

        if retry_config:
            cls.DEFAULT_RETRY.update(retry_config)

    @classmethod
    async def get(cls, url: str, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _get():
            async with cls.get_client() as client:
                response = await client.get(url, **kwargs)
                response.raise_for_status()
                return response

        try:
            return await _get()
        except httpx.HTTPStatusError as e:
            logger.warning(f"Request GET {url} failed after retries: {e}")
            return None

    @classmethod
    async def post(cls, url: str, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _post():
            async with cls.get_client() as client:
                response = await client.post(url, json=json, **kwargs)
                response.raise_for_status()
                return response

        try:
            return await _post()
        except Exception as e:
            logger.warning(f"Request POST {url} failed after retries: {e}")
            return None

    @classmethod
    async def delete(cls, url: str, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _delete():
            async with cls.get_client() as client:
                response = await client.delete(url, **kwargs)
                response.raise_for_status()
                return response

        try:
            return await _delete()
        except Exception as e:
            logger.warning(f"Request DELETE {url} failed after retries: {e}")
            return None
