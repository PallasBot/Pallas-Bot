"""Dispatch-level e2e: real patched_handle_event_now with the bridge scope.

Real NoneBot OneBot Bot/Adapter, real global matcher registry/rules/handlers,
real classification/route/selection, real capture/forward and the real
send-queue hook are exercised. Only external leaves are stubbed: DB/claim/scrub
leaves, the ACL/plugin-switch/availability leaves, and the adapter's final
``_call_api``. No bridge/capture/forward/send/dispatch core is replaced.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import nonebot
import pytest
from aiohttp import WSMsgType, web
from nonebot import matcher as nb_matcher
from nonebot import message as nb_message
from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message
from nonebot.rule import TrieRule

from pallas.core.platform.ingress import matcher_dispatch as md
from pallas.core.platform.ingress import send_queue
from pallas.product.agent_bridge import runtime
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

BOT_ID = 10001
OTHER_BOT = 10002
GROUP_ID = 700001
OTHER_GROUP = 700002
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


def _event(*, user_id=7, group_id=GROUP_ID, message_id=123, text="synthetic text", to_me=False, self_id=BOT_ID):
    return GroupMessageEvent(
        time=1800000000,
        self_id=self_id,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=message_id,
        user_id=user_id,
        message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": user_id, "nickname": "a", "card": "", "role": "member"},
        group_id=group_id,
        to_me=to_me,
    )


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


@pytest.fixture
def framework_state():
    saved_matchers = {p: list(v) for p, v in nb_matcher.matchers.items()}
    saved_event_pre = set(nb_message._event_preprocessors)
    saved_event_post = set(nb_message._event_postprocessors)
    saved_run_pre = set(nb_message._run_preprocessors)
    saved_run_post = set(nb_message._run_postprocessors)
    saved_trie = dict(TrieRule.prefix)
    nb_matcher.matchers.clear()
    nb_message._event_preprocessors.clear()
    nb_message._event_postprocessors.clear()
    nb_message._run_preprocessors.clear()
    nb_message._run_postprocessors.clear()
    yield
    nb_matcher.matchers.clear()
    for priority, classes in saved_matchers.items():
        nb_matcher.matchers[priority] = list(classes)
    nb_message._event_preprocessors.clear()
    nb_message._event_preprocessors.update(saved_event_pre)
    nb_message._event_postprocessors.clear()
    nb_message._event_postprocessors.update(saved_event_post)
    nb_message._run_preprocessors.clear()
    nb_message._run_preprocessors.update(saved_run_pre)
    nb_message._run_postprocessors.clear()
    nb_message._run_postprocessors.update(saved_run_post)
    TrieRule.prefix.clear()
    TrieRule.prefix.update(saved_trie)


@pytest.fixture
async def qq_queue(monkeypatch):
    sent: list[dict] = []
    counter = {"n": 0}

    async def recorder(_adapter, bot, api, **data):
        counter["n"] += 1
        sent.append({"bot": bot.self_id, "api": api, "data": data})
        return {"message_id": 500000 + counter["n"]}

    monkeypatch.setattr(send_queue, "send_queue_enabled", lambda: True)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    monkeypatch.setattr(Adapter, "_call_api", recorder)
    send_queue.install_send_queue()
    await send_queue.start_send_queue_workers()
    bot = Bot(Adapter(nonebot.get_driver()), self_id=str(BOT_ID))
    monkeypatch.setattr(runtime, "get_bot", lambda _id: bot)
    try:
        yield SimpleNamespace(bot=bot, sent=sent)
    finally:
        await send_queue.stop_send_queue_workers()
        send_queue.uninstall_send_queue()


@pytest.fixture(autouse=True)
async def _reset_runtime():
    runtime._owner_config = None
    runtime._bridge = None
    runtime.clear_bridge_runtime_cache()
    md._BRIDGE_SUPPRESSED_MATCHERS = None
    send_queue.reset_send_queue_for_tests()
    try:
        yield
    finally:
        await runtime.stop_bridge()
        send_queue.reset_send_queue_for_tests()
        runtime.clear_bridge_runtime_cache()
        md._BRIDGE_SUPPRESSED_MATCHERS = None
        _restore_plugin_names()
        from pallas.core.platform.ingress.plugin_command_plaintext import clear_plugin_command_plaintext_cache

        clear_plugin_command_plaintext_cache()


_SAVED_PLUGIN_NAMES: dict[int, object] = {}


def _register_pool():
    from packages.llm_chat.chat_message import llm_chat_msg
    from packages.repeater.handlers.message import any_msg

    for matcher, canonical in ((any_msg, "repeater"), (llm_chat_msg, "llm_chat")):
        if id(matcher) not in _SAVED_PLUGIN_NAMES:
            _SAVED_PLUGIN_NAMES[id(matcher)] = (matcher, getattr(matcher, "plugin_name", None))
        matcher.plugin_name = canonical
    pool = nb_matcher.matchers
    for matcher in (any_msg, llm_chat_msg):
        bucket = pool.setdefault(int(matcher.priority), [])
        if matcher not in bucket:
            bucket.append(matcher)


def _restore_plugin_names():
    for matcher, original in _SAVED_PLUGIN_NAMES.values():
        matcher.plugin_name = original
    _SAVED_PLUGIN_NAMES.clear()


def _patch_boundaries(monkeypatch, *, kernel_calls, captures, llm_probe, stale=False, cold_start=False):
    from packages.repeater.handlers import message as repeater_message

    async def execute_repeater_message(_bot, event):
        from pallas.core.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext

        if is_plugin_command_plaintext(str(event.get_plaintext() or "")):
            return  # matches the real early command skip
        kernel_calls.append("repeater")

    def availability() -> bool:
        # llm_chat.chat_message uses a synchronous module-local alias of this.
        llm_probe.append("llm")
        return False

    monkeypatch.setattr(repeater_message, "execute_repeater_message", execute_repeater_message)
    monkeypatch.setattr("packages.llm_chat.chat_message.is_llm_chat_service_enabled", availability)
    monkeypatch.setattr(md, "_apply_rage_gate", _false)
    monkeypatch.setattr(md, "stale_message_drop_needed", lambda _event: stale)
    monkeypatch.setattr(md, "is_overloaded", lambda: False)
    monkeypatch.setattr(md, "in_cold_start_window", lambda: cold_start)

    class _Action:
        async def run(self) -> None:
            captures.append("run")

    async def build_ctx(_bot_id, _event):
        return SimpleNamespace(plain_body="synthetic text", norm_raw="synthetic text", sharding_active=False)

    async def scrub(**_kwargs):
        return False

    monkeypatch.setattr(repeater_message, "build_repeater_event_context", build_ctx)
    monkeypatch.setattr(repeater_message, "is_message_scrub_blocked_async", scrub)
    monkeypatch.setattr(
        "pallas.product.llm.reply_target_candidates.record_reply_target_candidate",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "packages.repeater.message_runtime_handler.build_repeater_capture_and_learn_action",
        lambda _event, _chat: _Action(),
    )
    monkeypatch.setattr(runtime, "group_output_refusal", _no_refusal)
    monkeypatch.setattr("pallas.core.perm.check.satisfies_command_permission", _allow)


async def _false(*_args, **_kwargs):
    return False


async def _allow(*_args, **_kwargs):
    return True


async def _no_refusal(*_args, **_kwargs):
    return None


async def _arm_bridge(monkeypatch, fake_mai, *, live_patch=True):
    owner = _config(url=fake_mai.url)
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: owner)
    if live_patch:
        monkeypatch.setattr(runtime, "_live_config_or_none", lambda: owner)
    assert await runtime.start_bridge() is True
    await fake_mai.wait_connected()


async def _wait(predicate, within: float = 2.0) -> None:
    async with asyncio.timeout(within):
        while not predicate():  # noqa: ASYNC110 - bounded poll on recorded side effects
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("to_me", [False, True])
async def test_scope_owned_chat_captures_forwards_and_echoes(monkeypatch, framework_state, fake_mai, qq_queue, to_me):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe)
    await _arm_bridge(monkeypatch, fake_mai)

    bot = qq_queue.bot
    await md.patched_handle_event_now(bot, _event(text="hello mai", to_me=to_me))

    assert captures == ["run"]  # real capture ran exactly once
    assert kernel_calls == []  # old repeater kernel not called
    assert llm_probe == []  # real llm_chat matcher suppressed before its rule
    await _wait(lambda: fake_mai.frames())
    assert fake_mai.frames()[0]["message_segment"] == {"type": "text", "data": "hello mai"}

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
    await _wait(lambda: qq_queue.sent)
    assert qq_queue.sent[0]["api"] == "send_group_msg"
    assert qq_queue.sent[0]["data"]["group_id"] == GROUP_ID
    await _wait(lambda: fake_mai.frames(echo=True))
    assert fake_mai.frames(echo=True)[0]["content"] == {
        "type": "echo",
        "echo": "mai-out-1",
        "actual_id": "500001",
    }


@pytest.mark.parametrize("to_me", [False, True])
async def test_multi_account_scope_suppresses_every_owned_account(
    monkeypatch, framework_state, fake_mai, qq_queue, to_me
):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe)
    owner = _config(url=fake_mai.url, bot_id=0, bot_ids=frozenset({BOT_ID, OTHER_BOT}))
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: owner)
    monkeypatch.setattr(runtime, "_live_config_or_none", lambda: owner)
    assert await runtime.start_bridge() is True
    await fake_mai.wait_connected()

    other = Bot(Adapter(nonebot.get_driver()), self_id=str(OTHER_BOT))
    await md.patched_handle_event_now(other, _event(self_id=OTHER_BOT, to_me=to_me))

    assert captures == ["run"]  # both owned accounts capture exactly once
    assert kernel_calls == []  # old repeater kernel not called for the peer account
    assert llm_probe == []  # old llm_chat matcher suppressed before its rule
    await _wait(lambda: fake_mai.frames())
    assert fake_mai.frames()[0]["account_id"] == str(OTHER_BOT)
    assert fake_mai.frames()[0]["message_info"]["additional_config"]["account_id"] == str(OTHER_BOT)


async def test_scope_owned_command_runs_but_is_not_forwarded(monkeypatch, framework_state, fake_mai, qq_queue):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    command_calls: list[str] = []
    _register_pool()
    from pallas.api.commands import bind_alias_handlers, group_command

    cmd = group_command("bridge.testcmd", "桥测试", cd_sec=0, priority=5, block=False)

    async def _handler(_ctx) -> None:
        command_calls.append("cmd")

    bind_alias_handlers(cmd, _handler)
    from pallas.core.platform.ingress.plugin_command_plaintext import clear_plugin_command_plaintext_cache

    clear_plugin_command_plaintext_cache()
    monkeypatch.setattr("pallas.core.commands.matcher.is_command_cooldown_ready", _allow)
    monkeypatch.setattr("pallas.core.commands.matcher.refresh_command_cooldown", _noop)
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe)
    await _arm_bridge(monkeypatch, fake_mai)

    await md.patched_handle_event_now(qq_queue.bot, _event(text="/桥测试"))

    assert command_calls == ["cmd"]  # real command handler executed
    assert captures == []  # command lane is not captured/forwarded
    assert kernel_calls == []  # old repeater kernel self-skips commands
    assert fake_mai.frames() == []


async def _noop(*_args, **_kwargs):
    return None


@pytest.mark.parametrize("to_me", [False, True])
async def test_out_of_scope_chat_reaches_the_old_agent(monkeypatch, framework_state, fake_mai, qq_queue, to_me):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe)
    await _arm_bridge(monkeypatch, fake_mai)

    # positive control: the same matchers ARE reachable for a non-owned group
    await md.patched_handle_event_now(qq_queue.bot, _event(group_id=OTHER_GROUP, to_me=to_me))

    assert kernel_calls == ["repeater"]  # old repeater path reachable
    assert llm_probe == ["llm"]  # llm_chat rule evaluated, probe reachable
    assert captures == []
    assert fake_mai.frames() == []


async def test_scope_owned_stale_is_not_captured_or_forwarded(monkeypatch, framework_state, fake_mai, qq_queue):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe, stale=True)
    await _arm_bridge(monkeypatch, fake_mai)

    await md.patched_handle_event_now(qq_queue.bot, _event())

    assert captures == []
    assert fake_mai.frames() == []


async def test_scope_owned_degraded_captures_but_does_not_forward(monkeypatch, framework_state, fake_mai, qq_queue):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe, cold_start=True)
    await _arm_bridge(monkeypatch, fake_mai)

    await md.patched_handle_event_now(qq_queue.bot, _event())

    assert captures == ["run"]
    assert fake_mai.frames() == []


async def test_scope_owned_admission_deny_captures_without_forward(monkeypatch, framework_state, fake_mai, qq_queue):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()

    async def _refuse(*_args, **_kwargs):
        return "sleeping"

    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe)
    monkeypatch.setattr(runtime, "group_output_refusal", _refuse)
    await _arm_bridge(monkeypatch, fake_mai)

    await md.patched_handle_event_now(qq_queue.bot, _event())

    assert captures == ["run"]  # still captured
    assert kernel_calls == []  # old agent still suppressed
    assert fake_mai.frames() == []  # but not forwarded


async def test_scope_owned_live_invalid_suppresses_old_agent_without_forward(
    monkeypatch, framework_state, fake_mai, qq_queue
):
    kernel_calls: list[str] = []
    captures: list[str] = []
    llm_probe: list[str] = []
    _register_pool()
    _patch_boundaries(monkeypatch, kernel_calls=kernel_calls, captures=captures, llm_probe=llm_probe)
    await _arm_bridge(monkeypatch, fake_mai, live_patch=False)
    invalid = {
        "MAIBOT_BRIDGE_ENABLED": "true",
        "MAIBOT_BRIDGE_URL": "garbage",
        "MAIBOT_BRIDGE_BOT_ID": str(BOT_ID),
        "MAIBOT_BRIDGE_GROUP_IDS": f"[{GROUP_ID}]",
        "MAIBOT_BRIDGE_PLATFORM": PLATFORM,
    }
    monkeypatch.setattr(runtime, "repo_env_raw_value", lambda key: invalid.get(key))
    runtime.clear_bridge_runtime_cache()

    await md.patched_handle_event_now(qq_queue.bot, _event())

    assert captures == ["run"]
    assert kernel_calls == []  # ownership retained: old chat still suppressed
    assert fake_mai.frames() == []  # invalid live config refuses communication
