"""Focused tests for capture_repeater_only (bridge scope capture path)."""

from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from packages.repeater.handlers import message as repeater_message

GROUP_ID = 700001


def _event() -> GroupMessageEvent:
    return GroupMessageEvent.model_validate({
        "time": 1800000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 123,
        "group_id": GROUP_ID,
        "user_id": 7,
        "message": "synthetic text",
        "raw_message": "synthetic text",
        "font": 0,
        "sender": {"user_id": 7, "nickname": "synthetic user", "role": "member"},
    })


class _FakeAction:
    def __init__(self) -> None:
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1


def _patch_capture(monkeypatch, *, ctx, action, scrub=False, record=None):
    async def build_repeater_event_context(_bot_id, _event):
        return ctx

    async def is_message_scrub_blocked_async(**_kwargs):
        return scrub

    def record_reply_target_candidate(**_kwargs):
        if record is not None:
            record.append(_kwargs)

    monkeypatch.setattr(repeater_message, "build_repeater_event_context", build_repeater_event_context)
    monkeypatch.setattr(repeater_message, "is_message_scrub_blocked_async", is_message_scrub_blocked_async)
    monkeypatch.setattr(repeater_message, "Chat", lambda _event: object())
    monkeypatch.setattr(
        "pallas.product.llm.reply_target_candidates.record_reply_target_candidate",
        record_reply_target_candidate,
    )
    monkeypatch.setattr(
        "packages.repeater.message_runtime_handler.build_repeater_capture_and_learn_action",
        lambda _event, _chat: action,
    )


async def test_capture_only_runs_capture_action_once(monkeypatch):
    action = _FakeAction()
    ctx = SimpleNamespace(plain_body="hello", norm_raw="hello", sharding_active=False)
    _patch_capture(monkeypatch, ctx=ctx, action=action)

    captured = await repeater_message.capture_repeater_only(SimpleNamespace(self_id=10001), _event())
    assert captured is True
    assert action.runs == 1


async def test_capture_only_returns_false_when_context_missing(monkeypatch):
    action = _FakeAction()
    _patch_capture(monkeypatch, ctx=None, action=action)

    captured = await repeater_message.capture_repeater_only(SimpleNamespace(self_id=10001), _event())
    assert captured is False
    assert action.runs == 0


async def test_capture_only_skips_when_scrubbed(monkeypatch):
    action = _FakeAction()
    ctx = SimpleNamespace(plain_body="bad", norm_raw="bad", sharding_active=False)
    _patch_capture(monkeypatch, ctx=ctx, action=action, scrub=True)

    captured = await repeater_message.capture_repeater_only(SimpleNamespace(self_id=10001), _event())
    assert captured is False
    assert action.runs == 0
