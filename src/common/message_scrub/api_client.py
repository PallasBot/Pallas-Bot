"""可选 HTTP 审查：POST JSON，返回 {\"blocked\": bool}。"""

from __future__ import annotations

import os
from typing import Any

import httpx
from nonebot import logger


def _api_fail_open() -> bool:
    v = os.getenv("PALLAS_INBOUND_FILTER_API_FAIL_OPEN", "1").strip().lower()
    return v in ("1", "true", "yes", "on", "")


def _api_headers() -> dict[str, str]:
    key = os.getenv("PALLAS_INBOUND_FILTER_API_KEY", "").strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _scrub_api_url() -> str:
    for key in ("PALLAS_SCRUB_API_URL", "PALLAS_INBOUND_FILTER_API_URL"):
        u = os.getenv(key, "").strip()
        if u:
            return u
    return ""


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


async def api_scrub_blocked(*, plain_text: str, raw_message: str) -> bool:
    url = _scrub_api_url()
    if not url:
        return False
    try:
        timeout_sec = float(os.getenv("PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC", "2"))
    except ValueError:
        timeout_sec = 2.0
    payload = {"plain_text": plain_text or "", "raw_message": raw_message or ""}
    fail_open = _api_fail_open()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_sec), trust_env=True) as client:
            r = await client.post(url, json=payload, headers=_api_headers())
    except Exception as e:
        logger.debug("message_scrub API request failed: {}", e)
        return not fail_open
    if r.status_code != 200:
        logger.debug("message_scrub API non-200: {} {}", r.status_code, r.text[:200] if r.text else "")
        return not fail_open
    try:
        body = r.json()
    except Exception as e:
        logger.debug("message_scrub API JSON parse failed: {}", e)
        return not fail_open
    blocked = _coerce_blocked(body)
    if blocked is None:
        logger.debug('message_scrub API missing or invalid "blocked" bool in body')
        return not fail_open
    return blocked
