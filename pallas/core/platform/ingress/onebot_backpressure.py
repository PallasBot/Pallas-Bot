from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, cast

from nonebot.adapters.onebot.v11.adapter import Adapter
from nonebot.adapters.onebot.v11.bot import Bot
from nonebot.adapters.onebot.v11.utils import log
from nonebot.exception import WebSocketClosed
from nonebot.utils import escape_tag

from pallas.core.platform.ingress.conversation_scheduler import wait_for_conversation_capacity

_ORIGINAL_HANDLE_WS: Any = None
_ORIGINAL_HANDLE_HTTP: Any = None
_PATCHED = False


async def patched_handle_ws(adapter: Adapter, websocket: Any) -> None:
    self_id = websocket.request.headers.get("x-self-id")
    if not self_id:
        log("WARNING", "Missing X-Self-ID Header")
        await websocket.close(1008, "Missing X-Self-ID Header")
        return
    if self_id in adapter.bots:
        log("WARNING", f"There's already a bot {self_id}, ignored")
        await websocket.close(1008, "Duplicate X-Self-ID")
        return
    response = adapter._check_access_token(websocket.request)
    if response is not None:
        await websocket.close(1008, cast("str", response.content))
        return

    await websocket.accept()
    bot = Bot(adapter, self_id)
    adapter.bot_connect(bot)
    adapter.connections[self_id] = websocket
    log("INFO", f"<y>Bot {escape_tag(self_id)}</y> connected")
    try:
        while True:
            data = await websocket.receive()
            if event := adapter.json_to_event(json.loads(data)):
                await wait_for_conversation_capacity(bot, event)
                task = asyncio.create_task(bot.handle_event(event))
                task.add_done_callback(adapter.tasks.discard)
                adapter.tasks.add(task)
    except WebSocketClosed:
        log("WARNING", f"WebSocket for Bot {escape_tag(self_id)} closed by peer")
    except Exception as exc:
        log(
            "ERROR",
            f"<r><bg #f8bbd0>Error while process data from websocket for bot {escape_tag(self_id)}.</bg #f8bbd0></r>",
            exc,
        )
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
        adapter.connections.pop(self_id, None)
        adapter.bot_disconnect(bot)


async def patched_handle_http(adapter: Adapter, request: Any) -> Any:
    self_id = request.headers.get("x-self-id")
    if not self_id:
        log("WARNING", "Missing X-Self-ID Header")
        from nonebot.drivers import Response

        return Response(400, content="Missing X-Self-ID Header")
    response = adapter._check_signature(request)
    if response is not None:
        return response
    if not request.content:
        from nonebot.drivers import Response

        return Response(400, content="Invalid request body")
    event = adapter.json_to_event(json.loads(request.content))
    if event:
        bot = adapter.bots.get(self_id)
        if bot is None:
            bot = Bot(adapter, self_id)
            adapter.bot_connect(bot)
            log("INFO", f"<y>Bot {escape_tag(self_id)}</y> connected")
        bot = cast("Bot", bot)
        await wait_for_conversation_capacity(bot, event)
        task = asyncio.create_task(bot.handle_event(event))
        task.add_done_callback(adapter.tasks.discard)
        adapter.tasks.add(task)
    from nonebot.drivers import Response

    return Response(204)


def install_onebot_backpressure() -> None:
    global _ORIGINAL_HANDLE_HTTP, _ORIGINAL_HANDLE_WS, _PATCHED
    if _PATCHED:
        return
    _ORIGINAL_HANDLE_WS = Adapter._handle_ws
    _ORIGINAL_HANDLE_HTTP = Adapter._handle_http
    Adapter._handle_ws = patched_handle_ws  # type: ignore[method-assign]
    Adapter._handle_http = patched_handle_http  # type: ignore[method-assign]
    _PATCHED = True


def uninstall_onebot_backpressure() -> None:
    global _ORIGINAL_HANDLE_HTTP, _ORIGINAL_HANDLE_WS, _PATCHED
    if not _PATCHED:
        return
    Adapter._handle_ws = _ORIGINAL_HANDLE_WS
    Adapter._handle_http = _ORIGINAL_HANDLE_HTTP
    _ORIGINAL_HANDLE_HTTP = None
    _ORIGINAL_HANDLE_WS = None
    _PATCHED = False
