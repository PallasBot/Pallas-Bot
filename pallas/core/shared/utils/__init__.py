import asyncio
from typing import Any

import httpx
from nonebot import get_bot, logger
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential


async def is_bot_admin(bot_id: int, group_id: int, no_cache: bool = False) -> bool:
    """查询该牛牛在群内是否为 QQ 群管理员或群主"""
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
    }

    @classmethod
    async def _ensure_client(cls) -> httpx.AsyncClient:
        async with cls._lock:
            if cls._client is None or cls._client.is_closed:
                cls._client = httpx.AsyncClient(
                    timeout=cls.DEFAULT_TIMEOUT,
                )
            return cls._client

    @classmethod
    async def _reset_client(cls) -> None:
        async with cls._lock:
            if cls._client and not cls._client.is_closed:
                await cls._client.aclose()
            cls._client = None

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

    @staticmethod
    def _transport_error_message(e: httpx.TransportError) -> str:
        detail = str(e).strip()
        if not detail:
            detail = repr(e)
        return f"httpx client transport error [{type(e).__name__}]: {detail}"

    @classmethod
    async def get(cls, url: str, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _get():
            client = await cls._ensure_client()
            try:
                response = await client.get(url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.TransportError as e:
                logger.error(cls._transport_error_message(e))
                await cls._reset_client()
                raise

        try:
            return await _get()
        except httpx.HTTPStatusError as e:
            logger.warning(f"Request GET {url} failed after retries: {e}")
            return None
        except RetryError as e:
            if isinstance(e.__cause__, httpx.TransportError):
                logger.warning(f"Request GET {url} failed after retries: {cls._transport_error_message(e.__cause__)}")
                return None
            raise

    @classmethod
    async def post(cls, url: str, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _post():
            client = await cls._ensure_client()
            try:
                response = await client.post(url, json=json, **kwargs)
                response.raise_for_status()
                return response
            except httpx.TransportError as e:
                logger.error(cls._transport_error_message(e))
                await cls._reset_client()
                raise

        try:
            return await _post()
        except Exception as e:
            logger.warning(f"Request POST {url} failed after retries: {e}")
            return None

    @classmethod
    async def put(cls, url: str, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _put():
            client = await cls._ensure_client()
            try:
                response = await client.put(url, json=json, **kwargs)
                response.raise_for_status()
                return response
            except httpx.TransportError as e:
                logger.error(cls._transport_error_message(e))
                await cls._reset_client()
                raise

        try:
            return await _put()
        except Exception as e:
            logger.warning(f"Request PUT {url} failed after retries: {e}")
            return None

    @classmethod
    async def delete(cls, url: str, **kwargs) -> httpx.Response | None:
        @retry(**cls.DEFAULT_RETRY)
        async def _delete():
            client = await cls._ensure_client()
            try:
                response = await client.delete(url, **kwargs)
                response.raise_for_status()
                return response
            except httpx.TransportError as e:
                logger.error(cls._transport_error_message(e))
                await cls._reset_client()
                raise

        try:
            return await _delete()
        except Exception as e:
            logger.warning(f"Request DELETE {url} failed after retries: {e}")
            return None
