"""Focused tests for the MaiBot bridge ingress wiring and capture-only path."""

from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.core.platform.ingress import matcher_dispatch

GROUP_ID = 700001
OTHER_GROUP = 700002


def _group_event(group_id: int) -> GroupMessageEvent:
    return GroupMessageEvent.model_validate({
        "time": 1800000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 123,
        "group_id": group_id,
        "user_id": 7,
        "message": "synthetic text",
        "raw_message": "synthetic text",
        "font": 0,
        "sender": {"user_id": 7, "nickname": "synthetic user", "role": "member"},
    })


def test_suppressed_matchers_only_exclude_repeater_capture():
    from packages.repeater.handlers.message import any_msg

    suppressed = matcher_dispatch.bridge_suppressed_matchers()
    # bridge captures once; only the repeater capture matcher is suppressed.
    assert any_msg in suppressed
    # the retired llm_chat generation matcher no longer exists
    assert not hasattr(__import__("packages.llm_chat.chat_message", fromlist=["x"]), "llm_chat_msg")


def test_bridge_owned_group_event_follows_runtime(monkeypatch):
    monkeypatch.setattr(
        "pallas.product.agent_bridge.runtime.bridge_owns",
        lambda bot_id, group_id: group_id == GROUP_ID and bot_id == 10001,
    )
    bot = SimpleNamespace(self_id="10001")
    other_bot = SimpleNamespace(self_id="10002")
    assert matcher_dispatch.bridge_owned_group_event(bot, _group_event(GROUP_ID)) is True
    assert matcher_dispatch.bridge_owned_group_event(bot, _group_event(OTHER_GROUP)) is False
    assert matcher_dispatch.bridge_owned_group_event(other_bot, _group_event(GROUP_ID)) is False


async def test_capture_and_forward_captures_once_then_forwards(monkeypatch):
    calls: list[object] = []

    async def fake_capture(_bot, _event):
        calls.append("capture")
        return True

    async def fake_forward(_bot, _event, *, command_traffic):
        calls.append(("forward", command_traffic))
        return True

    monkeypatch.setattr("packages.repeater.handlers.message.capture_repeater_only", fake_capture)
    monkeypatch.setattr("pallas.product.agent_bridge.runtime.forward_owned_event", fake_forward)

    await matcher_dispatch.run_bridge_owned_capture_and_forward(object(), SimpleNamespace(), degraded=False)
    assert calls == ["capture", ("forward", False)]


async def test_capture_and_forward_skips_forward_when_degraded(monkeypatch):
    calls: list[object] = []

    async def fake_capture(_bot, _event):
        calls.append("capture")
        return True

    async def fake_forward(_bot, _event, *, command_traffic):
        calls.append("forward")
        return True

    monkeypatch.setattr("packages.repeater.handlers.message.capture_repeater_only", fake_capture)
    monkeypatch.setattr("pallas.product.agent_bridge.runtime.forward_owned_event", fake_forward)

    await matcher_dispatch.run_bridge_owned_capture_and_forward(object(), SimpleNamespace(), degraded=True)
    assert calls == ["capture"]
