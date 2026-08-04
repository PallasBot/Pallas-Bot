from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from nonebot.adapters.onebot.v11.adapter import Adapter
from nonebot.adapters.onebot.v11.event import LifecycleMetaEvent
from nonebot.exception import WebSocketClosed

from pallas.core.platform.ingress import onebot_backpressure


class FakeBot:
    def __init__(self, adapter, self_id: str) -> None:
        self.adapter = adapter
        self.self_id = self_id
        self.handled = asyncio.Event()

    async def handle_event(self, event) -> None:
        self.handled.set()


class ReverseWebSocket:
    def __init__(self) -> None:
        self.request = SimpleNamespace(headers={"x-self-id": "10001"})
        self.received = 0

    async def accept(self) -> None:
        return None

    async def close(self, *args) -> None:
        return None

    async def receive(self) -> str:
        self.received += 1
        if self.received <= 2:
            return json.dumps({"event": self.received})
        raise WebSocketClosed


class ForwardWebSocket:
    def __init__(self) -> None:
        self.received = 0

    async def receive(self) -> str:
        self.received += 1
        if self.received <= 2:
            return json.dumps({"event": self.received})
        raise WebSocketClosed


class ForwardConnection:
    def __init__(self, websocket: ForwardWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> ForwardWebSocket:
        return self.websocket

    async def __aexit__(self, *args) -> None:
        return None


def adapter_stub() -> SimpleNamespace:
    return SimpleNamespace(
        bots={},
        tasks=set(),
        connections={},
        _check_access_token=lambda _request: None,
        _check_signature=lambda _request: None,
        bot_connect=lambda _bot: None,
        bot_disconnect=lambda _bot: None,
    )


def install_fake_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onebot_backpressure, "Bot", FakeBot)


@pytest.mark.asyncio
async def test_reverse_ws_waits_before_reading_next_frame_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = adapter_stub()
    websocket = ReverseWebSocket()
    first_dispatched = asyncio.Event()
    release_capacity = asyncio.Event()

    async def reserve(_bot, _event):
        return object()

    async def wait_for_capacity(_bot, event) -> None:
        if isinstance(event, LifecycleMetaEvent):
            return
        await release_capacity.wait()

    async def run_reserved(bot, _event, _reservation) -> None:
        await bot.handle_event(_event)
        first_dispatched.set()

    install_fake_bot(monkeypatch)
    monkeypatch.setattr(onebot_backpressure, "reserve_conversation_capacity", reserve)
    monkeypatch.setattr(onebot_backpressure, "wait_for_conversation_capacity", wait_for_capacity)
    monkeypatch.setattr(onebot_backpressure, "run_conversation_event_with_reservation", run_reserved)
    adapter.json_to_event = lambda _data: object()

    task = asyncio.create_task(onebot_backpressure.patched_handle_ws(adapter, websocket))
    await first_dispatched.wait()
    await asyncio.sleep(0)

    assert websocket.received == 1

    release_capacity.set()
    await task


@pytest.mark.asyncio
async def test_http_response_waits_for_capacity_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = adapter_stub()
    request = SimpleNamespace(headers={"x-self-id": "10001"}, content=json.dumps({"event": 1}))
    release_capacity = asyncio.Event()

    async def reserve(_bot, _event):
        await release_capacity.wait()
        return object()

    async def run_reserved(bot, event, _reservation) -> None:
        await bot.handle_event(event)

    install_fake_bot(monkeypatch)
    monkeypatch.setattr(onebot_backpressure, "reserve_conversation_capacity", reserve)
    monkeypatch.setattr(onebot_backpressure, "run_conversation_event_with_reservation", run_reserved)
    adapter.json_to_event = lambda _data: object()

    response_task = asyncio.create_task(onebot_backpressure.patched_handle_http(adapter, request))
    await asyncio.sleep(0)

    assert response_task.done() is False

    release_capacity.set()
    response = await response_task
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_forward_ws_waits_before_reading_next_frame_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = adapter_stub()
    websocket = ForwardWebSocket()
    first_dispatched = asyncio.Event()
    release_capacity = asyncio.Event()
    lifecycle = LifecycleMetaEvent.model_validate(
        {
            "time": 1,
            "self_id": 10001,
            "post_type": "meta_event",
            "meta_event_type": "lifecycle",
            "sub_type": "connect",
        }
    )

    async def reserve(_bot, _event):
        return object()

    async def wait_for_capacity(_bot, event) -> None:
        if isinstance(event, LifecycleMetaEvent):
            return
        await release_capacity.wait()

    async def run_reserved(bot, event, _reservation) -> None:
        await bot.handle_event(event)
        if not isinstance(event, LifecycleMetaEvent):
            first_dispatched.set()

    install_fake_bot(monkeypatch)
    monkeypatch.setattr(onebot_backpressure, "reserve_conversation_capacity", reserve)
    monkeypatch.setattr(onebot_backpressure, "wait_for_conversation_capacity", wait_for_capacity)
    monkeypatch.setattr(onebot_backpressure, "run_conversation_event_with_reservation", run_reserved)
    adapter.json_to_event = lambda data: lifecycle if data["event"] == 1 else object()
    adapter.onebot_config = SimpleNamespace(onebot_access_token=None)
    adapter.websocket = lambda _request: ForwardConnection(websocket)

    task = asyncio.create_task(onebot_backpressure.patched_forward_ws(adapter, "ws://example.test"))
    await first_dispatched.wait()
    await asyncio.sleep(0)

    assert websocket.received == 2

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_install_and_uninstall_onebot_backpressure() -> None:
    original = Adapter._handle_ws
    original_http = Adapter._handle_http
    original_forward = Adapter._forward_ws
    onebot_backpressure.uninstall_onebot_backpressure()
    try:
        onebot_backpressure.install_onebot_backpressure()
        assert Adapter._handle_ws is onebot_backpressure.patched_handle_ws
        assert Adapter._handle_http is onebot_backpressure.patched_handle_http
        assert Adapter._forward_ws is onebot_backpressure.patched_forward_ws
        onebot_backpressure.uninstall_onebot_backpressure()
        assert Adapter._handle_ws is original
        assert Adapter._handle_http is original_http
        assert Adapter._forward_ws is original_forward
    finally:
        onebot_backpressure.uninstall_onebot_backpressure()
