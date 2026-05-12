from __future__ import annotations

import asyncio
import time
from urllib.parse import urlencode

import httpx
from nonebot import logger

from ..config import get_message_scrub_config
from ..quiet_http_loggers import scrub_http_log_noise
from ..shared_httpx import get_scrub_async_httpx_client

_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_DEFAULT_CENSOR_URL = "https://aip.baidubce.com/rest/2.0/solution/v1/text_censor/v2/user_defined"

_token_lock = asyncio.Lock()
_token: str | None = None
_token_deadline: float = 0.0


def clear_baidu_token_cache() -> None:
    """供 ``reload_message_scrub_caches`` 调用，避免换密钥后仍用旧 token。"""
    global _token, _token_deadline
    _token = None
    _token_deadline = 0.0


def _censor_url() -> str:
    cfg = get_message_scrub_config()
    return cfg.scrub_baidu_censor_url or _DEFAULT_CENSOR_URL


def _strategy_id() -> str | None:
    s = get_message_scrub_config().scrub_baidu_strategy_id
    return s or None


def _combined_text(*, plain_text: str, raw_message: str) -> str:
    p = (plain_text or "").strip()
    if p:
        return p
    return (raw_message or "").strip()


async def _ensure_token(client: httpx.AsyncClient, *, post_timeout: httpx.Timeout) -> str:
    global _token, _token_deadline
    async with _token_lock:
        now = time.time()
        if _token and now < _token_deadline - 60:
            return _token
        cfg = get_message_scrub_config()
        ak, sk = cfg.scrub_baidu_api_key, cfg.scrub_baidu_secret_key
        if not ak or not sk:
            raise RuntimeError("baidu keys missing")
        q = urlencode({"grant_type": "client_credentials", "client_id": ak, "client_secret": sk})
        url = f"{_TOKEN_URL}?{q}"
        r = await client.post(url, timeout=post_timeout)
        if r.status_code != 200:
            logger.debug("baidu token non-200: {} {}", r.status_code, r.text[:200] if r.text else "")
            raise RuntimeError("baidu token http")
        data = r.json()
        if not isinstance(data, dict) or "access_token" not in data:
            logger.debug("baidu token body invalid: {}", str(data)[:200])
            raise RuntimeError("baidu token body")
        token = str(data["access_token"])
        try:
            expires_in = int(data.get("expires_in", 2592000))
        except (TypeError, ValueError):
            expires_in = 2592000
        _token = token
        _token_deadline = now + max(expires_in, 300)
        return token


def _parse_conclusion_blocked(data: dict[str, object]) -> bool | None:
    """True=拦截，False=放行，None=无法解析。"""
    block_suspected = get_message_scrub_config().scrub_baidu_block_suspected
    ct = data.get("conclusionType")
    if isinstance(ct, (int, float)):
        n = int(ct)
        if n == 1:
            return False
        if n == 2:
            return True
        if n == 3:
            return block_suspected
        if n == 4:
            return False
        return None
    conc = data.get("conclusion")
    if isinstance(conc, str):
        c = conc.strip()
        if c == "合规":
            return False
        if c == "不合规":
            return True
        if c == "疑似":
            return block_suspected
        if c == "审核失败":
            return False
    return None


class BaiduTextReviewProvider:
    """百度智能云文本审核（``text_censor`` v2 user_defined），以官方 ``conclusion`` / ``conclusionType`` 为准。"""

    id = "baidu"

    async def is_blocked(self, *, plain_text: str, raw_message: str) -> bool:
        text = _combined_text(plain_text=plain_text, raw_message=raw_message)
        if not text:
            return False
        max_bytes = 20000
        encoded = text.encode("utf-8")
        if len(encoded) > max_bytes:
            text = encoded[:max_bytes].decode("utf-8", errors="ignore")

        timeout_sec = get_message_scrub_config().inbound_filter_api_timeout_sec
        req_timeout = httpx.Timeout(timeout_sec)

        async with scrub_http_log_noise():
            client = await get_scrub_async_httpx_client()
            token = await _ensure_token(client, post_timeout=req_timeout)
            base = _censor_url()
            sep = "&" if "?" in base else "?"
            post_url = f"{base}{sep}access_token={token}"
            form: dict[str, str] = {"text": text}
            sid = _strategy_id()
            if sid:
                form["strategyId"] = sid
            r = await client.post(
                post_url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=req_timeout,
            )
        if r.status_code != 200:
            logger.debug("baidu censor non-200: {} {}", r.status_code, r.text[:200] if r.text else "")
            raise RuntimeError("baidu censor http")
        try:
            body = r.json()
        except Exception as e:
            logger.debug("baidu censor JSON error: {}", e)
            raise
        if not isinstance(body, dict):
            raise RuntimeError("baidu censor body")
        if "error_code" in body:
            logger.debug("baidu censor error: {}", body)
            raise RuntimeError("baidu business error")
        blocked = _parse_conclusion_blocked(body)
        if blocked is None:
            logger.debug("baidu censor unknown shape: {}", str(body)[:300])
            raise RuntimeError("baidu unknown response")
        return blocked
