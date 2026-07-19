"""分片 hub：将 MAA getTask / reportStatus 转发到登记 worker。"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from nonebot import logger

from pallas.core.platform.shard.coord.maa_route_registry import (
    register_maa_user_route,
    resolve_worker_port_for_maa_user,
)


async def forward_maa_json_post(
    user: str,
    path: str,
    json_body: dict[str, Any],
    *,
    timeout_sec: float = 30.0,
) -> tuple[int, Any]:
    port = resolve_worker_port_for_maa_user(user)
    if port is None:
        return 200, None

    url = f"http://127.0.0.1:{int(port)}{path}"
    timeout = httpx.Timeout(timeout_sec, connect=min(10.0, timeout_sec))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=json_body)
    except httpx.HTTPError as err:
        logger.warning("maa forward user={} port={} path={}: {}", user, port, path, err)
        raise HTTPException(status_code=502, detail="MAA worker unreachable") from err

    try:
        body = resp.json()
    except Exception:
        body = {"message": "ok"}
    if user.strip():
        register_maa_user_route(user, worker_port=int(port))
    return resp.status_code, body
