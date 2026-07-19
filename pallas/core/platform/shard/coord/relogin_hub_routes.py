"""分片 hub：worker 私聊 relogin 口令 HTTP 入口。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI  # noqa: TC002
from nonebot import logger
from pydantic import BaseModel, Field

from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule
from pallas.core.platform.shard.coord.relogin_constants import RELOGIN_HUB_PATH
from pallas.core.platform.shard.coord.relogin_payload import result_to_payload

_mounted = False


class ReloginMessageBody(BaseModel):
    bot_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    text: str = ""


async def hub_relogin_message(body: ReloginMessageBody) -> dict[str, Any]:
    service = import_plugin_submodule("relogin_bot", "service")
    handle_relogin_message = service.handle_relogin_message

    result = await handle_relogin_message(
        bot_id=body.bot_id.strip(),
        user_id=body.user_id.strip(),
        text=body.text or "",
    )
    return result_to_payload(result)


def mount_relogin_hub_routes(app: FastAPI) -> None:
    global _mounted
    if _mounted:
        return
    app.add_api_route(
        RELOGIN_HUB_PATH,
        hub_relogin_message,
        methods=["POST"],
        name="shard_relogin_message",
    )
    _mounted = True
    logger.info("relogin hub route mounted: {}", RELOGIN_HUB_PATH)
