"""Acceptance tests for the original offline MaiBot text bridge.

A local aiohttp server stands in for the legacy MessageServer and a fake
``send_reply`` stands in for the Pallas delivery path. Nothing here starts
MaiBot, QQ, a model, or a real account.
"""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parents[3]
BRIDGE_PATH = ROOT / "pallas/product/agent_bridge/transport.py"
PROBE = ROOT / "tools/experiments/maibot_spike/native_bridge_probe.py"

BOT_ID = 10001
GROUP_ID = 700001
OTHER_GROUP = 700002
USER_ID = 7
PLATFORM = "pallas-qq"


def _load_bridge():
    spec = importlib.util.spec_from_file_location("maibot_native_bridge", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["maibot_native_bridge"] = module
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge()


class FakeMaiBotServer:
    def __init__(self) -> None:
        self.received: list[dict] = []
        self.connections = 0
        self.platform_header: str | None = None
        self.authorization_header: str | None = None
        self.ws = None
        self.url = ""
        self._connected = asyncio.Event()

    async def handler(self, request):
        self.connections += 1
        self.platform_header = request.headers.get("platform")
        self.authorization_header = request.headers.get("authorization")
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

    async def send_frame(self, payload: dict) -> None:
        await self.ws.send_str(json.dumps(payload, ensure_ascii=False))

    async def send_raw(self, raw: str) -> None:
        await self.ws.send_str(raw)

    async def close_connection(self) -> None:
        await self.ws.close()


class FakeReply:
    def __init__(self, result: int = 987654321, error: Exception | None = None) -> None:
        self.calls: list[tuple[int, int, str]] = []
        self.result = result
        self.error = error

    async def __call__(self, bot_id: int, group_id: int, text: str) -> int:
        self.calls.append((bot_id, group_id, text))
        if self.error is not None:
            raise self.error
        return self.result


def _scope(**overrides):
    params = {
        "enabled": True,
        "bot_id": BOT_ID,
        "allowed_group_ids": frozenset({GROUP_ID}),
        "platform": PLATFORM,
    }
    params.update(overrides)
    return bridge.BridgeScope(**params)


def _onebot_event(**overrides):
    event = {
        "time": 1800000000,
        "self_id": BOT_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 123,
        "group_id": GROUP_ID,
        "user_id": USER_ID,
        "message": "synthetic text",
        "raw_message": "synthetic text",
        "font": 0,
        "sender": {"user_id": USER_ID, "nickname": "synthetic user", "role": "member"},
    }
    event.update(overrides)
    return event


def _reply_frame(
    *,
    internal_id: str,
    platform: str = PLATFORM,
    group_id: int = GROUP_ID,
    text: str = "synthetic reply",
    account_id: int = BOT_ID,
    omit_account: bool = False,
    segment: dict | None = None,
):
    info = {
        "platform": platform,
        "message_id": internal_id,
        "time": 1800000001.0,
        "group_info": {"platform": platform, "group_id": str(group_id)},
        "user_info": {"platform": platform, "user_id": str(USER_ID)},
    }
    if not omit_account:
        info["additional_config"] = {"account_id": str(account_id)}
    return {
        "message_info": info,
        "message_segment": segment if segment is not None else {"type": "text", "data": text},
    }


def _echoes(server: FakeMaiBotServer) -> list[dict]:
    return [frame for frame in server.received if frame.get("is_custom_message")]


async def _wait_until(predicate, within: float = 2.0) -> None:
    async with asyncio.timeout(within):
        while not predicate():  # noqa: ASYNC110 - bounded poll on recorded side effects
            await asyncio.sleep(0.01)


@pytest.fixture
async def fake_server():
    server = FakeMaiBotServer()
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


async def test_disabled_scope_opens_no_connection_and_sends_nothing(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(bridge.BridgeScope(), reply)

    with pytest.raises(bridge.BridgeDisabledError):
        await instance.connect(fake_server.url)
    with pytest.raises(bridge.BridgeDisabledError):
        await instance.forward_event(_onebot_event(), command_traffic=False)

    assert fake_server.connections == 0
    assert fake_server.received == []
    assert reply.calls == []


async def test_single_account_text_round_trip_echoes_the_real_message_id(fake_server):
    reply = FakeReply(result=555000111)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url, token="synthetic-token")
    await fake_server.wait_connected()
    assert fake_server.platform_header == PLATFORM
    assert fake_server.authorization_header == "synthetic-token"

    await instance.forward_event(_onebot_event(message="hello mai"), command_traffic=False)
    await _wait_until(lambda: len(fake_server.received) == 1)
    inbound = fake_server.received[0]
    assert inbound["message_info"]["platform"] == PLATFORM
    assert inbound["message_info"]["message_id"] == "123"
    assert inbound["message_info"]["group_info"]["group_id"] == str(GROUP_ID)
    assert inbound["message_info"]["user_info"]["user_id"] == str(USER_ID)
    assert inbound["message_info"]["additional_config"]["account_id"] == str(BOT_ID)
    assert inbound["message_segment"] == {"type": "text", "data": "hello mai"}

    await fake_server.send_frame(_reply_frame(internal_id="mai-msg-1", text="hi there"))
    await _wait_until(lambda: reply.calls)
    assert reply.calls == [(BOT_ID, GROUP_ID, "hi there")]
    await _wait_until(lambda: _echoes(fake_server))
    echo = _echoes(fake_server)[0]
    assert echo["platform"] == PLATFORM
    assert echo["message_type_name"] == "message_id_echo"
    assert echo["is_custom_message"] is True
    assert echo["content"] == {"type": "echo", "echo": "mai-msg-1", "actual_id": "555000111"}

    await instance.close()


async def test_command_traffic_is_never_forwarded(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await instance.forward_event(_onebot_event(message="/status"), command_traffic=True)
    await asyncio.sleep(0.1)

    assert fake_server.received == []
    await instance.close()


async def test_forged_identity_and_cross_group_events_are_rejected(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await instance.forward_event(_onebot_event(self_id=999), command_traffic=False)
    await instance.forward_event(_onebot_event(group_id=OTHER_GROUP), command_traffic=False)
    await instance.forward_event(_onebot_event(user_id=0), command_traffic=False)
    await instance.forward_event(_onebot_event(message_id=-1), command_traffic=False)
    await instance.forward_event(_onebot_event(message="[CQ:at,qq=1] hi"), command_traffic=False)
    await asyncio.sleep(0.1)

    assert fake_server.received == []
    assert len(instance.errors) >= 5
    await instance.close()


async def test_reply_with_wrong_platform_is_rejected(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="x", platform="other-qq"))
    await _wait_until(lambda: instance.errors)

    assert reply.calls == []
    assert _echoes(fake_server) == []
    await instance.close()


async def test_missing_account_id_is_usable_but_a_conflicting_one_is_rejected(fake_server):
    reply = FakeReply(result=42)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="ok", omit_account=True))
    await _wait_until(lambda: reply.calls)
    assert reply.calls == [(BOT_ID, GROUP_ID, "synthetic reply")]

    await fake_server.send_frame(_reply_frame(internal_id="bad", account_id=999))
    await asyncio.sleep(0.1)
    assert len(reply.calls) == 1
    assert instance.errors
    await instance.close()


async def test_non_text_illegal_empty_and_overlong_frames_are_rejected(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="a", segment={"type": "image", "data": "http://x"}))
    await fake_server.send_frame(
        _reply_frame(
            internal_id="b",
            segment={"type": "seglist", "data": [{"type": "text", "data": "hi"}, {"type": "at", "data": "1"}]},
        )
    )
    await fake_server.send_frame(_reply_frame(internal_id="c", text=""))
    await fake_server.send_frame(_reply_frame(internal_id="d", text="x" * 5000))
    await fake_server.send_raw("not json{")
    await fake_server.send_raw(json.dumps([1, 2, 3]))
    await asyncio.sleep(0.2)

    assert reply.calls == []
    assert _echoes(fake_server) == []
    assert len(instance.errors) >= 6
    await instance.close()


async def test_flat_text_seglist_is_accepted(fake_server):
    reply = FakeReply(result=7)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(
        _reply_frame(
            internal_id="seg",
            segment={"type": "seglist", "data": [{"type": "text", "data": "ab"}, {"type": "text", "data": "cd"}]},
        )
    )
    await _wait_until(lambda: reply.calls)

    assert reply.calls == [(BOT_ID, GROUP_ID, "abcd")]
    await instance.close()


async def test_duplicate_outbound_frame_calls_the_callback_once(fake_server):
    reply = FakeReply(result=1)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    frame = _reply_frame(internal_id="dup")
    await fake_server.send_frame(frame)
    await _wait_until(lambda: len(reply.calls) == 1)
    await fake_server.send_frame(frame)
    await asyncio.sleep(0.15)

    assert len(reply.calls) == 1
    assert len(_echoes(fake_server)) == 1
    await instance.close()


async def test_duplicate_inbound_event_is_forwarded_once(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    event = _onebot_event(message_id=123)
    await instance.forward_event(event, command_traffic=False)
    await instance.forward_event(event, command_traffic=False)
    await asyncio.sleep(0.1)

    assert len(fake_server.received) == 1
    await instance.close()


async def test_callback_failure_is_observable_and_not_echoed(fake_server):
    reply = FakeReply(error=RuntimeError("synthetic delivery failure"))
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="fail", text="please fail"))
    await _wait_until(lambda: instance.errors)

    assert reply.calls == [(BOT_ID, GROUP_ID, "please fail")]
    assert _echoes(fake_server) == []
    assert any("send_reply failed" in error for error in instance.errors)
    await instance.close()


async def test_non_positive_receipt_is_not_echoed(fake_server):
    reply = FakeReply(result=0)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="zero"))
    await _wait_until(lambda: instance.errors)

    assert reply.calls
    assert _echoes(fake_server) == []
    await instance.close()


async def test_disconnect_fails_explicitly_without_replay(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.close_connection()
    await asyncio.wait_for(instance.wait_closed(), timeout=2)
    assert instance.connected is False

    with pytest.raises(bridge.BridgeNotConnectedError):
        await instance.forward_event(_onebot_event(), command_traffic=False)

    assert fake_server.connections == 1
    assert reply.calls == []
    await instance.close()


async def test_close_cancels_the_reader_and_leaves_no_tasks(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await instance.stop()
    await instance.close()  # idempotent

    leftover = [
        task.get_name()
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done() and task.get_name() == "maibot-bridge.read"
    ]
    assert leftover == []
    assert instance.connected is False


async def test_outbound_cq_and_blank_text_are_rejected(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await instance.forward_event(_onebot_event(message="[CQ:at,qq=all]"), command_traffic=False)
    await instance.forward_event(_onebot_event(message_id=124, message="   "), command_traffic=False)
    await instance.forward_event(_onebot_event(message_id=125, message="[cq:face,id=1]"), command_traffic=False)
    await asyncio.sleep(0.1)

    assert fake_server.received == []
    assert len(instance.errors) >= 3
    await instance.close()


async def test_inbound_cq_and_blank_text_are_not_delivered_or_echoed(fake_server):
    reply = FakeReply(result=5)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="cq", text="[CQ:at,qq=all]"))
    await fake_server.send_frame(_reply_frame(internal_id="blank", text="   "))
    await _wait_until(lambda: len(instance.errors) >= 2)

    assert reply.calls == []
    assert _echoes(fake_server) == []
    await instance.close()


async def test_invalid_id_strings_do_not_kill_the_reader(fake_server):
    reply = FakeReply(result=9)
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    bad_group = _reply_frame(internal_id="badgroup")
    bad_group["message_info"]["group_info"]["group_id"] = "²"
    await fake_server.send_frame(bad_group)
    huge_group = _reply_frame(internal_id="hugegroup")
    huge_group["message_info"]["group_info"]["group_id"] = "9" * 40
    await fake_server.send_frame(huge_group)
    await fake_server.send_frame(_reply_frame(internal_id="i" * 300))
    await fake_server.send_frame(_reply_frame(internal_id="good", text="still alive"))
    await _wait_until(lambda: reply.calls)

    assert reply.calls == [(BOT_ID, GROUP_ID, "still alive")]
    assert len(instance.errors) >= 3
    await instance.close()


def test_scope_rejects_non_bool_enabled():
    with pytest.raises(ValueError, match="enabled must be a bool"):
        bridge.BridgeScope(enabled="false", bot_id=BOT_ID, allowed_group_ids=frozenset({GROUP_ID}), platform=PLATFORM)


async def test_reader_failure_is_observable_and_close_still_closes_the_session(fake_server, monkeypatch):
    async def failing_reader(self, ws):
        raise RuntimeError("synthetic reader failure")

    monkeypatch.setattr(bridge.MaiBotBridge, "_read_loop", failing_reader)
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()
    await asyncio.sleep(0.05)

    await instance.close()

    assert instance.connected is False
    assert any("reader" in error for error in instance.errors)
    assert instance._session is None
    leftover = [
        task.get_name()
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done() and task.get_name() == "maibot-bridge.read"
    ]
    assert leftover == []


async def test_stop_cancels_a_blocking_callback(fake_server):
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking(bot_id, group_id, text):
        started.set()
        await release.wait()
        return 1

    instance = bridge.MaiBotBridge(_scope(), blocking)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="block"))
    await asyncio.wait_for(started.wait(), timeout=2)
    await asyncio.wait_for(instance.stop(), timeout=2)

    assert instance.connected is False
    release.set()


async def test_shared_source_id_across_allowed_groups_is_forwarded_twice(fake_server):
    reply = FakeReply()
    scope = _scope(allowed_group_ids=frozenset({GROUP_ID, OTHER_GROUP}))
    instance = bridge.MaiBotBridge(scope, reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await instance.forward_event(_onebot_event(group_id=GROUP_ID, message_id=5), command_traffic=False)
    await instance.forward_event(_onebot_event(group_id=OTHER_GROUP, message_id=5), command_traffic=False)
    await asyncio.sleep(0.1)

    groups = {frame["message_info"]["group_info"]["group_id"] for frame in fake_server.received}
    assert len(fake_server.received) == 2
    assert groups == {str(GROUP_ID), str(OTHER_GROUP)}
    await instance.close()


async def test_shared_outbound_id_across_allowed_groups_calls_the_callback_twice(fake_server):
    reply = FakeReply(result=3)
    scope = _scope(allowed_group_ids=frozenset({GROUP_ID, OTHER_GROUP}))
    instance = bridge.MaiBotBridge(scope, reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    await fake_server.send_frame(_reply_frame(internal_id="shared", group_id=GROUP_ID))
    await fake_server.send_frame(_reply_frame(internal_id="shared", group_id=OTHER_GROUP))
    await _wait_until(lambda: len(reply.calls) == 2)

    assert sorted(group for _, group, _ in reply.calls) == sorted([GROUP_ID, OTHER_GROUP])
    await instance.close()


async def test_onebot_array_text_message_is_forwarded(fake_server):
    reply = FakeReply()
    instance = bridge.MaiBotBridge(_scope(), reply)
    await instance.connect(fake_server.url)
    await fake_server.wait_connected()

    array_message = [{"type": "text", "data": {"text": "ab"}}, {"type": "text", "data": {"text": "cd"}}]
    await instance.forward_event(_onebot_event(message=array_message), command_traffic=False)
    await _wait_until(lambda: fake_server.received)
    assert fake_server.received[0]["message_segment"] == {"type": "text", "data": "abcd"}

    await instance.forward_event(
        _onebot_event(message_id=200, message=[{"type": "image", "data": {"file": "x"}}]),
        command_traffic=False,
    )
    await asyncio.sleep(0.1)
    assert len(fake_server.received) == 1
    await instance.close()


def test_probe_runs_against_the_real_legacy_server_and_exits_naturally(tmp_path):
    python = Path(os.environ.get("MAIM_MESSAGE_PYTHON", "/tmp/opencode/maim068/venv/bin/python"))
    if not python.is_file():
        pytest.skip("isolated maim-message environment required to load the real legacy server")
    try:
        result = subprocess.run(
            [str(python), str(PROBE)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        pytest.fail(f"native bridge probe did not exit naturally:\n{stdout}\n{stderr}")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "NATIVE_BRIDGE_PROBE=PASS" in output
    assert "MaiBot main program was NOT started" in output
