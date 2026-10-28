"""Multi-account wire tests for one shared WebSocket (single transport).

Real ``MaiBotBridge`` transport against a local aiohttp "FakeMai" legacy server;
only the send callback is a recording stub. No bridge/transport logic is mocked.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import WSMsgType, web

from pallas.product.agent_bridge.transport import BridgeScope, MaiBotBridge

BOT_A = 10001
BOT_B = 10002
GROUP_ID = 700001
OTHER_GROUP = 700002
PLATFORM = "pallas-qq"


def _scope(*bots: int, groups=(GROUP_ID,)) -> BridgeScope:
    return BridgeScope(enabled=True, bot_ids=frozenset(bots), allowed_group_ids=frozenset(groups), platform=PLATFORM)


def _event(*, self_id: int, user_id: int = 7, group_id: int = GROUP_ID, message_id: int = 123, text="hello mai"):
    return {
        "time": 1800000000,
        "self_id": self_id,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": message_id,
        "group_id": group_id,
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "font": 0,
    }


def _reply(*, account_id: object = None, sender: object = "7", message_id: str = "mai-out-1", text="hi there"):
    info: dict = {
        "platform": PLATFORM,
        "message_id": message_id,
        "time": 1800000001.0,
        "group_info": {"platform": PLATFORM, "group_id": str(GROUP_ID)},
        "user_info": {"platform": PLATFORM},
    }
    if sender is not None:
        info["user_info"]["user_id"] = str(sender)
    if account_id is not None:
        info["additional_config"] = {"account_id": str(account_id)}
    return {"message_info": info, "message_segment": {"type": "text", "data": text}}


class FakeMai:
    def __init__(self) -> None:
        self.received: list[dict] = []
        self.ws = None
        self._connected = asyncio.Event()
        self.url = ""

    async def handler(self, request):
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


async def _wait(predicate, within: float = 2.0) -> None:
    async with asyncio.timeout(within):
        while not predicate():  # noqa: ASYNC110 - bounded poll on recorded side effects
            await asyncio.sleep(0.01)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str]] = []

    async def __call__(self, bot_id: int, group_id: int, text: str) -> int:
        self.calls.append((bot_id, group_id, text))
        return 900000 + len(self.calls)


async def _connected_bridge(scope: BridgeScope, fake_mai) -> tuple[MaiBotBridge, Recorder]:
    recorder = Recorder()
    bridge = MaiBotBridge(scope, recorder)
    await bridge.connect(fake_mai.url)
    await fake_mai.wait_connected()
    return bridge, recorder


async def test_multi_inbound_namespaces_id_and_keeps_original(fake_mai):
    bridge, _ = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await bridge.forward_event(_event(self_id=BOT_A, message_id=555), command_traffic=False)
        await _wait(lambda: fake_mai.frames())
        frame = fake_mai.frames()[0]
        assert frame["account_id"] == str(BOT_A)
        assert frame["message_info"]["message_id"] == f"pallas:{BOT_A}:{GROUP_ID}:555"
        assert frame["message_info"]["additional_config"] == {
            "account_id": str(BOT_A),
            "original_message_id": "555",
        }
    finally:
        await bridge.close()


async def test_same_group_same_original_id_two_accounts_both_forward(fake_mai):
    bridge, _ = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await bridge.forward_event(_event(self_id=BOT_A, message_id=777), command_traffic=False)
        await bridge.forward_event(_event(self_id=BOT_B, message_id=777), command_traffic=False)
        await _wait(lambda: len(fake_mai.frames()) == 2)
        ids = {frame["message_info"]["message_id"] for frame in fake_mai.frames()}
        assert ids == {f"pallas:{BOT_A}:{GROUP_ID}:777", f"pallas:{BOT_B}:{GROUP_ID}:777"}
    finally:
        await bridge.close()


async def test_inbound_filters_managed_peer_account(fake_mai):
    bridge, _ = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await bridge.forward_event(_event(self_id=BOT_A, user_id=BOT_B), command_traffic=False)
        await asyncio.sleep(0.05)
        assert fake_mai.frames() == []
        await bridge.forward_event(_event(self_id=BOT_A, user_id=7), command_traffic=False)
        await _wait(lambda: fake_mai.frames())
        assert len(fake_mai.frames()) == 1
    finally:
        await bridge.close()


async def test_multi_outbound_routes_by_explicit_account_claim(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=BOT_B, sender=BOT_B))
        await _wait(lambda: recorder.calls)
        assert recorder.calls[0][0] == BOT_B
        await asyncio.sleep(0.05)
        assert fake_mai.frames(echo=True) == []  # multi-account: never echo
    finally:
        await bridge.close()


async def test_multi_outbound_routes_by_managed_bot_sender(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=None, sender=BOT_A))
        await _wait(lambda: recorder.calls)
        assert recorder.calls[0][0] == BOT_A
    finally:
        await bridge.close()


async def test_multi_outbound_missing_identity_refused(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=None, sender="7"))  # human, not a managed account
        await asyncio.sleep(0.05)
        assert recorder.calls == []
        assert any("identity" in err for err in bridge.errors)
    finally:
        await bridge.close()


async def test_multi_outbound_conflicting_claims_refused(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=BOT_A, sender=BOT_B))
        await asyncio.sleep(0.05)
        assert recorder.calls == []
        assert any("conflict" in err for err in bridge.errors)
    finally:
        await bridge.close()


async def test_multi_outbound_unknown_account_refused(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=99999, sender=99999))
        await asyncio.sleep(0.05)
        assert recorder.calls == []
        assert any("unknown" in err for err in bridge.errors)
    finally:
        await bridge.close()


async def test_multi_outbound_unmanaged_sender_with_valid_claim_refused(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        # sender slot present but not a managed account: must not be ignored as a human
        await fake_mai.send(_reply(account_id=BOT_A, sender=999))
        await asyncio.sleep(0.05)
        assert recorder.calls == []
        assert any("sender" in err for err in bridge.errors)
    finally:
        await bridge.close()


async def test_multi_outbound_malformed_sender_with_valid_claim_refused(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=BOT_A, sender="not-an-id"))
        await asyncio.sleep(0.05)
        assert recorder.calls == []
        assert any("sender" in err for err in bridge.errors)
    finally:
        await bridge.close()


async def test_multi_outbound_missing_sender_allows_valid_claim(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=BOT_B, sender=None))
        await _wait(lambda: recorder.calls)
        assert recorder.calls[0][0] == BOT_B
    finally:
        await bridge.close()


async def test_outbound_dedup_is_per_account(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=BOT_A, sender=BOT_A, message_id="dup"))
        await _wait(lambda: len(recorder.calls) == 1)
        await fake_mai.send(_reply(account_id=BOT_A, sender=BOT_A, message_id="dup"))
        await asyncio.sleep(0.05)
        assert len(recorder.calls) == 1  # same account + internal id: no second send
        await fake_mai.send(_reply(account_id=BOT_B, sender=BOT_B, message_id="dup"))
        await _wait(lambda: len(recorder.calls) == 2)
        assert recorder.calls[1][0] == BOT_B  # other account, same internal id: sends
        assert fake_mai.frames(echo=True) == []
    finally:
        await bridge.close()


async def test_single_account_keeps_legacy_echo(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A), fake_mai)
    try:
        await fake_mai.send(_reply(account_id=None, sender="7", message_id="legacy-1"))
        await _wait(lambda: recorder.calls)
        assert recorder.calls[0][0] == BOT_A
        await _wait(lambda: fake_mai.frames(echo=True))
        assert fake_mai.frames(echo=True)[0]["content"]["echo"] == "legacy-1"
    finally:
        await bridge.close()


async def test_outbound_group_outside_allow_list_refused(fake_mai):
    bridge, recorder = await _connected_bridge(_scope(BOT_A, BOT_B), fake_mai)
    try:
        payload = _reply(account_id=BOT_A, sender=BOT_A)
        payload["message_info"]["group_info"]["group_id"] = str(OTHER_GROUP)
        await fake_mai.send(payload)
        await asyncio.sleep(0.05)
        assert recorder.calls == []
    finally:
        await bridge.close()


def test_scope_requires_positive_bot_ids():
    with pytest.raises(ValueError, match="bot_ids"):
        BridgeScope(enabled=True, bot_ids=frozenset(), allowed_group_ids=frozenset({GROUP_ID}), platform=PLATFORM)
