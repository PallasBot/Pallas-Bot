"""分片 worker：将私聊 relogin 口令转发至 hub。"""

from __future__ import annotations

import httpx
from nonebot import logger

from pallas.core.platform.shard.coord.relogin_constants import (
    RELOGIN_FORWARD_CONNECT_TIMEOUT_SEC,
    RELOGIN_FORWARD_TIMEOUT_SEC,
    RELOGIN_HUB_PATH,
)
from pallas.core.platform.shard.coord.relogin_payload import ReloginHandleResult, result_from_payload
from pallas.core.platform.shard.registry.config import get_shard_registry_settings


async def forward_relogin_to_hub(*, bot_id: str, user_id: str, text: str) -> ReloginHandleResult | None:
    port = get_shard_registry_settings().hub_port
    url = f"http://127.0.0.1:{int(port)}{RELOGIN_HUB_PATH}"
    payload = {"bot_id": str(bot_id), "user_id": str(user_id), "text": text or ""}
    timeout = httpx.Timeout(
        RELOGIN_FORWARD_TIMEOUT_SEC,
        connect=RELOGIN_FORWARD_CONNECT_TIMEOUT_SEC,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as err:
        logger.warning(
            "relogin forward bot={} user={} {}: {}",
            bot_id,
            user_id,
            type(err).__name__,
            err or repr(err),
        )
        return None

    if resp.status_code >= 400:
        logger.warning(
            "relogin forward bot={} user={} status={} body={}",
            bot_id,
            user_id,
            resp.status_code,
            resp.text[:200],
        )
        return None

    try:
        body = resp.json()
    except Exception:
        return ReloginHandleResult(replies=[])

    if not isinstance(body, dict):
        return ReloginHandleResult(replies=[])
    return result_from_payload(body)
