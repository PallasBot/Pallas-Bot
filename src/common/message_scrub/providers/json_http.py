from __future__ import annotations

from typing import Any

import httpx
from nonebot import logger

from ..config import get_message_scrub_config
from ..quiet_http_loggers import scrub_http_log_noise
from ..shared_httpx import get_scrub_async_httpx_client


def _coerce_blocked(body: Any) -> bool | None:
    if not isinstance(body, dict) or "blocked" not in body:
        return None
    v = body.get("blocked")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
        return None
    return None


class JsonHttpReviewProvider:
    """自建网关：POST JSON ``{plain_text, raw_message}``，响应 ``{blocked: bool}``。"""

    id = "json_http"

    def __init__(self, url: str) -> None:
        self._url = url

    def _headers(self) -> dict[str, str]:
        key = get_message_scrub_config().inbound_filter_api_key
        if not key:
            return {}
        return {"Authorization": f"Bearer {key}"}

    async def is_blocked(self, *, plain_text: str, raw_message: str) -> bool:
        cfg = get_message_scrub_config()
        timeout_sec = cfg.inbound_filter_api_timeout_sec
        req_timeout = httpx.Timeout(timeout_sec)
        payload = {"plain_text": plain_text or "", "raw_message": raw_message or ""}
        async with scrub_http_log_noise():
            client = await get_scrub_async_httpx_client()
            r = await client.post(self._url, json=payload, headers=self._headers(), timeout=req_timeout)
        if r.status_code != 200:
            logger.debug("json_http review non-200: {} {}", r.status_code, r.text[:200] if r.text else "")
            raise RuntimeError("json_http non-200")
        try:
            body = r.json()
        except Exception as e:
            logger.debug("json_http review JSON error: {}", e)
            raise
        blocked = _coerce_blocked(body)
        if blocked is None:
            logger.debug('json_http review missing invalid "blocked" in body')
            raise RuntimeError("json_http invalid body")
        return blocked
