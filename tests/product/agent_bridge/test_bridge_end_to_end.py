"""End-to-end MaiBot bridge test.

Real runtime, real transport, real send-queue workers and real
``send_group_message_with_receipt`` are exercised against a local aiohttp
"FakeMai" legacy WebSocket server and a FakeQQ bot. Only external boundaries are
stubbed: config source, DB/ACL/plugin-switch leaves, and the QQ adapter's final
``_call_api``. No bridge/transport/dispatch logic is mocked.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import WSMsgType, web
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.core.platform.ingress import send_queue
from pallas.product.agent_bridge import runtime
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

BOT_ID = 10001
OTHER_BOT = 10002
GROUP_ID = 700001
PLATFORM = "pallas-qq"


def _config(**overrides):
    base = {
        "enabled": True,
        "url": "ws://127.0.0.1:1/ws",
        "bot_id": BOT_ID,
        "group_ids": frozenset({GROUP_ID}),
        "platform": PLATFORM,
        "token": "",
    }
    base.update(overrides)
    return MaiBotBridgeConfig(**base)


def _event(*, user_id=7, group_id=GROUP_ID, message_id=123, text="synthetic text"):
    return GroupMessageEvent.model_validate({
        "time": 1800000000,
        "self_id": BOT_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": message_id,
        "group_id": group_id,
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "font": 0,
        "sender": {"user_id": user_id, "nickname": "synthetic user", "role": "member"},
    })


class FakeMai:
    def __init__(self) -> None:
        self.received: list[dict] = []
        self.ws = None
        self.platform_header: str | None = None
        self._connected = asyncio.Event()
        self.url = ""

    async def handler(self, request):
        self.platform_header = request.headers.get("platform")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws = ws
        self._connected.set()
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                self.received.append(json.loads(msg.data))
        return ws

    async def wait_connected(self) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=2)

    async def send(self, payload: dict) -> None:
        await self.ws.send_str(json.dumps(payload, ensure_ascii=False))

    def frames(self, *, echo: bool = False) -> list[dict]:
        return [frame for frame in self.received if bool(frame.get("is_custom_message")) is echo]


@pytest.fixture
async def fake_mai():
    server = FakeMai()
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
        if server.ws is not None and not server.ws.closed:
            await server.ws.close()
        await runner.cleanup()


@pytest.fixture(autouse=True)
async def _reset_bridge_runtime():
    runtime._owner_config = None
    runtime._bridge = None
    runtime.clear_bridge_runtime_cache()
    send_queue.reset_send_queue_for_tests()
    try:
        yield
    finally:
        await runtime.stop_bridge()
        await send_queue.stop_send_queue_workers()
        send_queue.reset_send_queue_for_tests()
        runtime.clear_bridge_runtime_cache()


class FakeQQBot:
    def __init__(self, self_id: int, adapter: object) -> None:
        self.self_id = str(self_id)
        self._adapter = adapter

    async def call_api(self, api: str, **data):
        return await send_queue.enqueue_call_api(self._adapter, self, api, **data)


@pytest.fixture
async def qq(monkeypatch):
    sent: list[dict] = []
    counter = {"n": 0}

    async def original(_adapter, bot, api, **data):
        counter["n"] += 1
        sent.append({"bot": bot.self_id, "api": api, "data": data})
        return {"message_id": 500000 + counter["n"]}

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", original)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    monkeypatch.setattr(send_queue, "send_queue_worker_count", lambda: 2)
    await send_queue.start_send_queue_workers()
    bot = FakeQQBot(BOT_ID, SimpleNamespace())
    monkeypatch.setattr(runtime, "get_bot", lambda _id: bot)
    try:
        yield SimpleNamespace(bot=bot, sent=sent)
    finally:
        await send_queue.stop_send_queue_workers()


def _install_leaf_gates(
    monkeypatch, *, disabled=False, sleeping=False, ban_allow=True, scrub_blocked=False, cmd_perm=True
):
    async def is_plugin_disabled(*_args, **_kwargs):
        return disabled

    class FakeBotConfig:
        def __init__(self, *_args, **_kwargs):
            pass

        async def is_sleep(self):
            return sleeping

    async def evaluate_acl(**_kwargs):
        return SimpleNamespace(source="rule", allow=ban_allow)

    async def query_group_ban_status_for_gate(_group_id):
        return not ban_allow

    async def is_message_scrub_blocked_async(**_kwargs):
        return scrub_blocked

    async def satisfies_command_permission(*_args, **_kwargs):
        return cmd_perm

    monkeypatch.setattr("packages.help.plugin_manager.is_plugin_disabled", is_plugin_disabled)
    monkeypatch.setattr("pallas.core.foundation.config.BotConfig", FakeBotConfig)
    monkeypatch.setattr("pallas.core.perm.acl.evaluate_acl", evaluate_acl)
    monkeypatch.setattr("packages.blacklist.ban_gate.query_group_ban_status_for_gate", query_group_ban_status_for_gate)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", is_message_scrub_blocked_async)
    monkeypatch.setattr("pallas.core.perm.check.satisfies_command_permission", satisfies_command_permission)


async def _start_bridge(monkeypatch, fake_mai, *, live_patch=True, **config_overrides):
    owner = _config(url=fake_mai.url, **config_overrides)
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: owner)
    if live_patch:
        monkeypatch.setattr(runtime, "_live_config_or_none", lambda: owner)
    assert await runtime.start_bridge() is True
    await fake_mai.wait_connected()


async def test_end_to_end_forward_and_real_id_echo(monkeypatch, fake_mai, qq):
    _install_leaf_gates(monkeypatch)
    await _start_bridge(monkeypatch, fake_mai)
    assert fake_mai.platform_header == PLATFORM

    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(text="hello mai"), command_traffic=False) is True
    await _wait(lambda: fake_mai.frames())
    inbound = fake_mai.frames()[0]
    assert inbound["message_info"]["group_info"]["group_id"] == str(GROUP_ID)
    assert inbound["message_info"]["additional_config"]["account_id"] == str(BOT_ID)
    assert inbound["message_segment"] == {"type": "text", "data": "hello mai"}

    await fake_mai.send({
        "message_info": {
            "platform": PLATFORM,
            "message_id": "mai-out-1",
            "time": 1800000001.0,
            "group_info": {"platform": PLATFORM, "group_id": str(GROUP_ID)},
            "user_info": {"platform": PLATFORM, "user_id": "7"},
        },
        "message_segment": {"type": "text", "data": "hi there"},
    })
    await _wait(lambda: qq.sent)
    assert qq.sent[0]["bot"] == str(BOT_ID)
    assert qq.sent[0]["api"] == "send_group_msg"
    assert qq.sent[0]["data"]["group_id"] == GROUP_ID
    await _wait(lambda: fake_mai.frames(echo=True))
    echo = fake_mai.frames(echo=True)[0]
    assert echo["message_type_name"] == "message_id_echo"
    assert echo["content"] == {"type": "echo", "echo": "mai-out-1", "actual_id": "500001"}


async def test_end_to_end_does_not_forward_another_bot_same_group(monkeypatch, fake_mai, qq):
    _install_leaf_gates(monkeypatch)
    await _start_bridge(monkeypatch, fake_mai)
    other = SimpleNamespace(self_id=str(OTHER_BOT))
    assert await runtime.forward_owned_event(other, _event(), command_traffic=False) is False
    assert (
        await runtime.forward_owned_event(
            SimpleNamespace(self_id=str(BOT_ID)), _event(user_id=BOT_ID), command_traffic=False
        )
        is False
    )
    assert fake_mai.frames() == []


@pytest.mark.parametrize(
    "live",
    [_config(enabled=False), _config(group_ids=frozenset()), _config(bot_id=OTHER_BOT)],
)
async def test_end_to_end_live_disable_or_move_group_keeps_scope_but_stops_io(monkeypatch, fake_mai, qq, live):
    _install_leaf_gates(monkeypatch)
    await _start_bridge(monkeypatch, fake_mai)
    monkeypatch.setattr(runtime, "_live_config_or_none", lambda: live)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert runtime.bridge_suppresses(BOT_ID, GROUP_ID) is True
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert fake_mai.frames() == []
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi")
    assert qq.sent == []
    assert fake_mai.frames(echo=True) == []


async def test_end_to_end_live_invalid_config_retains_scope_but_stops_io(monkeypatch, fake_mai, qq):
    _install_leaf_gates(monkeypatch)
    await _start_bridge(monkeypatch, fake_mai, live_patch=False)
    invalid = {
        "MAIBOT_BRIDGE_ENABLED": "true",
        "MAIBOT_BRIDGE_URL": "garbage",
        "MAIBOT_BRIDGE_BOT_ID": str(BOT_ID),
        "MAIBOT_BRIDGE_GROUP_IDS": f"[{GROUP_ID}]",
        "MAIBOT_BRIDGE_PLATFORM": PLATFORM,
    }
    monkeypatch.setattr(runtime, "repo_env_raw_value", lambda key: invalid.get(key))
    runtime.clear_bridge_runtime_cache()
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert runtime.bridge_suppresses(BOT_ID, GROUP_ID) is True
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi")
    assert fake_mai.frames() == []
    assert qq.sent == []
    assert fake_mai.frames(echo=True) == []


@pytest.mark.parametrize("gates", [{"disabled": True}, {"sleeping": True}, {"ban_allow": False}])
async def test_end_to_end_group_gate_blocks_forward_and_reply(monkeypatch, fake_mai, qq, gates):
    _install_leaf_gates(monkeypatch, **gates)
    await _start_bridge(monkeypatch, fake_mai)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert fake_mai.frames() == []
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi")


async def test_end_to_end_command_permission_refusal_blocks_forward(monkeypatch, fake_mai, qq):
    _install_leaf_gates(monkeypatch, cmd_perm=False)
    await _start_bridge(monkeypatch, fake_mai)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert fake_mai.frames() == []


async def test_end_to_end_scrub_blocks_reply_but_scope_retained(monkeypatch, fake_mai, qq):
    _install_leaf_gates(monkeypatch, scrub_blocked=True)
    await _start_bridge(monkeypatch, fake_mai)
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "bad text")
    assert qq.sent == []


async def test_end_to_end_shutdown_leaves_no_tasks(monkeypatch, fake_mai, qq):
    _install_leaf_gates(monkeypatch)
    await _start_bridge(monkeypatch, fake_mai)
    await runtime.stop_bridge()
    assert runtime._bridge is None
    assert runtime._owner_config is None
    leftover = [t.get_name() for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert "maibot-bridge.read" not in leftover


async def _wait(predicate, within: float = 2.0) -> None:
    async with asyncio.timeout(within):
        while not predicate():  # noqa: ASYNC110 - bounded poll on recorded side effects
            await asyncio.sleep(0.01)
