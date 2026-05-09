from __future__ import annotations

import httpx
from nonebot import logger

MAX_DREAM_IMAGE_BYTES = 6 * 1024 * 1024


async def download_image_url(url: str) -> bytes | None:
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=True) as client:
            r = await client.get(u)
            if r.status_code != 200:
                return None
            if len(r.content) > MAX_DREAM_IMAGE_BYTES:
                return None
            return r.content
    except Exception as e:
        logger.debug("dream image download failed: {}", e)
        return None
