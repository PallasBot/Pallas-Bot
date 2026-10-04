from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.kernel_runner import send_query_progress_after_delay


@pytest.fixture(autouse=True)
def allow_live_llm_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig

    cfg = LlmConfig(llm_chat_enabled=True)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)


@pytest.mark.asyncio
async def test_query_progress_sends_once_after_tool_call_started(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    finished = asyncio.Event()
    started.set()
    send = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.tool_loop.has_query_tool_schemas", lambda _schemas: True)
    monkeypatch.setattr("nonebot.get_bot", lambda _bot_id: SimpleNamespace(self_id="99"))
    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message", send)

    await send_query_progress_after_delay(
        started,
        finished,
        {
            "bot_id": 99,
            "group_id": 42,
            "speak_trigger": "to_me",
            "tool_schemas": [{"function": {"name": "demo__search"}}],
        },
        delay=0,
    )

    send.assert_awaited_once_with(SimpleNamespace(self_id="99"), 42, "我查一下。")


@pytest.mark.asyncio
async def test_query_progress_waits_for_a_late_tool_start(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    finished = asyncio.Event()
    send = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.product.llm.tool_loop.has_query_tool_schemas", lambda _schemas: True)
    monkeypatch.setattr("nonebot.get_bot", lambda _bot_id: SimpleNamespace(self_id="99"))
    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message", send)

    task = asyncio.create_task(
        send_query_progress_after_delay(
            started,
            finished,
            {
                "bot_id": 99,
                "group_id": 42,
                "speak_trigger": "to_me",
                "tool_schemas": [{"function": {"name": "demo__search"}}],
            },
            delay=0.02,
            request_started_at=0,
        )
    )
    await asyncio.sleep(0.03)
    assert send.await_count == 0
    started.set()
    await task

    send.assert_awaited_once_with(SimpleNamespace(self_id="99"), 42, "我查一下。")


@pytest.mark.asyncio
async def test_query_progress_rechecks_live_gate_after_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig

    started = asyncio.Event()
    finished = asyncio.Event()
    started.set()
    send = AsyncMock()
    live_cfg = {"value": LlmConfig(llm_chat_enabled=True)}

    async def wait_then_close(_awaitable, **kwargs):
        assert kwargs["timeout"] < 0.01
        if hasattr(_awaitable, "close"):
            _awaitable.close()
        live_cfg["value"] = LlmConfig(llm_chat_enabled=False)
        raise TimeoutError

    monkeypatch.setattr("pallas.product.llm.kernel_runner.asyncio.wait_for", wait_then_close)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: live_cfg["value"])
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)
    monkeypatch.setattr("pallas.product.llm.tool_loop.has_query_tool_schemas", lambda _schemas: True)
    monkeypatch.setattr("nonebot.get_bot", lambda _bot_id: SimpleNamespace(self_id="99"))
    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message", send)

    await send_query_progress_after_delay(
        started,
        finished,
        {
            "bot_id": 99,
            "group_id": 42,
            "speak_trigger": "to_me",
            "tool_schemas": [{"function": {"name": "demo__search"}}],
        },
        delay=0,
    )

    send.assert_not_awaited()
