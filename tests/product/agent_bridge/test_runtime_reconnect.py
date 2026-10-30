"""Runtime reconnect, readiness, and quiesce tests against local WebSockets."""

from __future__ import annotations

import asyncio
import json
import socket
from types import SimpleNamespace

import pytest
from aiohttp import WSMsgType, web
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.product.agent_bridge import runtime
from pallas.product.agent_bridge.config import MaiBotBridgeConfig
from pallas.product.agent_bridge.transport import BridgeScope, MaiBotBridge

BOT_ID = 10001
GROUP_ID = 700001
PLATFORM = "pallas-qq"


class LocalMai:
    def __init__(self, *, delay_handshake: bool = False) -> None:
        self.delay_handshake = delay_handshake
        self.release_handshake = asyncio.Event()
        if not delay_handshake:
            self.release_handshake.set()
        self.request_seen = asyncio.Event()
        self.headers: list[dict[str, str | None]] = []
        self.connections: list[web.WebSocketResponse] = []
        self.active = 0
        self.max_active = 0
        self.received: list[dict] = []
        self.url = ""

    async def handler(self, request):
        self.request_seen.set()
        self.headers.append({
            "platform": request.headers.get("platform"),
            "authorization": request.headers.get("authorization"),
        })
        await self.release_handshake.wait()
        ws = web.WebSocketResponse()
        try:
            await ws.prepare(request)
        except ConnectionResetError:
            return ws
        self.connections.append(ws)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    self.received.append(json.loads(msg.data))
        finally:
            self.active -= 1
        return ws

    async def wait_connections(self, count: int) -> None:
        await _wait(lambda: len(self.connections) >= count)


@pytest.fixture
async def mai():
    server = LocalMai()
    app = web.Application()
    app.router.add_get("/ws", server.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server.url = f"ws://127.0.0.1:{runner.addresses[0][1]}/ws"
    try:
        yield server
    finally:
        server.release_handshake.set()
        for ws in server.connections:
            if not ws.closed:
                await ws.close()
        await runner.cleanup()


@pytest.fixture(autouse=True)
async def reset_runtime():
    await runtime.stop_bridge()
    runtime.clear_bridge_runtime_cache()
    try:
        yield
    finally:
        await runtime.stop_bridge()
        runtime.clear_bridge_runtime_cache()


def _config(url: str, **overrides) -> MaiBotBridgeConfig:
    values = {
        "enabled": True,
        "url": url,
        "bot_id": BOT_ID,
        "group_ids": frozenset({GROUP_ID}),
        "platform": PLATFORM,
        "token": "",
    }
    values.update(overrides)
    return MaiBotBridgeConfig(**values)


def _arm(monkeypatch, config: MaiBotBridgeConfig) -> None:
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: config)
    monkeypatch.setattr(runtime, "_live_config_or_none", lambda: config)


def _event(message_id: int = 123) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate({
        "time": 1800000000,
        "self_id": BOT_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": message_id,
        "group_id": GROUP_ID,
        "user_id": 7,
        "message": [{"type": "text", "data": {"text": "synthetic text"}}],
        "raw_message": "synthetic text",
        "font": 0,
        "sender": {"user_id": 7, "nickname": "synthetic user", "role": "member"},
    })


async def _allow(*_args, **_kwargs) -> bool:
    return True


async def _no_refusal(*_args, **_kwargs) -> None:
    return None


def _install_forward_gates(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "group_output_refusal", _no_refusal)
    monkeypatch.setattr("pallas.core.perm.check.satisfies_command_permission", _allow)

    async def scrub(**_kwargs) -> bool:
        return False

    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", scrub)


async def _wait(predicate, within: float = 2.0) -> None:
    async with asyncio.timeout(within):
        while not predicate():  # noqa: ASYNC110 - bounded polling of local fixture state
            await asyncio.sleep(0.005)


async def test_start_arms_without_waiting_for_delayed_ws_and_ready_is_real(monkeypatch):
    mai = LocalMai(delay_handshake=True)
    app = web.Application()
    app.router.add_get("/ws", mai.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    mai.url = f"ws://127.0.0.1:{runner.addresses[0][1]}/ws"
    config = _config(mai.url, token="synthetic-token")
    _arm(monkeypatch, config)
    try:
        assert await asyncio.wait_for(runtime.start_bridge(), timeout=0.2) is True
        await mai.request_seen.wait()
        assert runtime.bridge_status()["state"] == "connecting"
        assert await runtime.wait_bridge_ready(timeout=0.01) is False

        mai.release_handshake.set()
        assert await runtime.wait_bridge_ready(timeout=1.0) is True
        assert runtime.bridge_status()["connected"] is True
        assert mai.headers == [{"platform": PLATFORM, "authorization": "synthetic-token"}]
    finally:
        mai.release_handshake.set()
        await runtime.stop_bridge()
        await runner.cleanup()


async def test_disconnect_reconnect_keeps_scope_and_does_not_replay(monkeypatch, mai):
    config = _config(mai.url)
    _arm(monkeypatch, config)
    _install_forward_gates(monkeypatch)
    monkeypatch.setattr(runtime, "RECONNECT_INITIAL_DELAY_SEC", 0.15)
    monkeypatch.setattr(runtime, "RECONNECT_MAX_DELAY_SEC", 0.15)

    assert await runtime.start_bridge() is True
    assert await runtime.wait_bridge_ready(timeout=1.0) is True
    bridge = runtime._bridge
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(1), command_traffic=False) is True
    await _wait(lambda: len(mai.received) == 1)

    await mai.connections[0].close()
    await _wait(lambda: mai.active == 0)
    await _wait(lambda: not bridge.connected)
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert await runtime.wait_bridge_ready(timeout=0.01) is False
    assert await runtime.forward_owned_event(bot, _event(2), command_traffic=False) is False
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "late reply")

    await mai.wait_connections(2)
    await _wait(lambda: bridge.connected)
    assert runtime._bridge is bridge
    assert mai.max_active == 1
    assert len(mai.received) == 1  # the event refused while offline was not replayed


async def test_startup_deadline_fails_closed_until_explicit_stop_and_rearm(monkeypatch, mai):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = _config(f"ws://127.0.0.1:{port}/ws")
    _arm(monkeypatch, config)
    monkeypatch.setattr(runtime, "STARTUP_DEADLINE_SEC", 0.03)
    monkeypatch.setattr(runtime, "CONNECT_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(runtime, "RECONNECT_INITIAL_DELAY_SEC", 0.2)
    monkeypatch.setattr(runtime, "RECONNECT_MAX_DELAY_SEC", 0.2)
    connect_calls = 0
    original_connect = runtime.MaiBotBridge.connect

    async def count_connect(self, *args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        await original_connect(self, *args, **kwargs)

    monkeypatch.setattr(runtime.MaiBotBridge, "connect", count_connect)
    assert await runtime.start_bridge() is True
    assert await runtime.wait_bridge_ready(timeout=0.5) is False
    assert runtime.bridge_status()["state"] == "startup_failed"
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert connect_calls == 1
    assert await runtime.start_bridge() is True
    assert connect_calls == 1

    await runtime.stop_bridge()
    config = _config(mai.url)
    _arm(monkeypatch, config)
    assert await runtime.start_bridge() is True
    assert await runtime.wait_bridge_ready(timeout=1.0) is True
    assert connect_calls == 2


async def test_quiesce_cancels_reader_retains_owner_and_stop_releases(monkeypatch, mai):
    config = _config(mai.url)
    _arm(monkeypatch, config)
    _install_forward_gates(monkeypatch)
    monkeypatch.setattr(runtime, "RECONNECT_INITIAL_DELAY_SEC", 0.01)
    assert await runtime.start_bridge() is True
    assert await runtime.wait_bridge_ready(timeout=1.0) is True
    bridge = runtime._bridge
    await mai.wait_connections(1)

    assert await runtime.start_bridge() is True
    assert runtime._bridge is bridge
    assert len(mai.connections) == 1
    changed = _config(mai.url, group_ids=frozenset({GROUP_ID + 1}))
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: changed)
    assert await runtime.start_bridge() is True
    assert runtime._owner_config is config
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    await runtime.quiesce_bridge()

    assert runtime.bridge_status()["state"] == "quiesced"
    assert await runtime.wait_bridge_ready(timeout=0.01) is False
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert bridge.connected is False
    assert bridge._session is None
    assert bridge._reader is None
    assert (
        await runtime.forward_owned_event(SimpleNamespace(self_id=str(BOT_ID)), _event(), command_traffic=False)
        is False
    )
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "late reply")

    await runtime.stop_bridge()
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is False
    assert runtime._bridge is None
    assert runtime.bridge_status()["state"] == "disabled"


async def test_wait_closed_propagates_caller_cancellation_without_canceling_reader(mai):
    bridge = MaiBotBridge(
        BridgeScope(enabled=True, bot_id=BOT_ID, allowed_group_ids=frozenset({GROUP_ID}), platform=PLATFORM),
        _allow,
    )
    await bridge.connect(mai.url)
    await mai.wait_connections(1)
    waiter = asyncio.create_task(bridge.wait_closed())
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert bridge._reader is not None
    assert not bridge._reader.done()
    await bridge.close()
    assert bridge._reader is None


async def test_quiesce_cancels_inflight_connect_and_backoff(monkeypatch, mai):
    mai.delay_handshake = True
    mai.release_handshake.clear()
    config = _config(mai.url)
    _arm(monkeypatch, config)
    monkeypatch.setattr(runtime, "STARTUP_DEADLINE_SEC", 5.0)
    assert await runtime.start_bridge() is True
    await mai.request_seen.wait()
    connector = runtime._connector_task
    await asyncio.wait_for(runtime.quiesce_bridge(), timeout=0.2)
    assert connector.done()
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert runtime._bridge._session is None

    await runtime.stop_bridge()

    # A failed initial attempt enters a cancellable backoff; quiesce must not wait it out.
    connect_started = asyncio.Event()

    async def fail_connect(*_args, **_kwargs):
        connect_started.set()
        raise OSError("synthetic failure")

    monkeypatch.setattr(runtime.MaiBotBridge, "connect", fail_connect)
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: config)
    monkeypatch.setattr(runtime, "RECONNECT_INITIAL_DELAY_SEC", 2.0)
    monkeypatch.setattr(runtime, "RECONNECT_MAX_DELAY_SEC", 2.0)
    assert await runtime.start_bridge() is True
    await connect_started.wait()
    connector = runtime._connector_task
    await asyncio.wait_for(runtime.quiesce_bridge(), timeout=0.2)
    assert connector.done()
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
