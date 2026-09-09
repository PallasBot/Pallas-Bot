from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.kernel_runner import send_query_progress_after_delay


@pytest.mark.asyncio
async def test_query_progress_sends_once_after_tool_call_started(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    started.set()
    send = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.tool_loop.has_query_tool_schemas", lambda _schemas: True)
    monkeypatch.setattr("nonebot.get_bot", lambda _bot_id: SimpleNamespace(self_id="99"))
    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message", send)

    await send_query_progress_after_delay(
        started,
        {
            "bot_id": 99,
            "group_id": 42,
            "speak_trigger": "to_me",
            "tool_schemas": [{"function": {"name": "demo__search"}}],
        },
        delay=0,
    )

    send.assert_awaited_once_with(SimpleNamespace(self_id="99"), 42, "我查一下。")
