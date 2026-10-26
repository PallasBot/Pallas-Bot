"""Real build_repeater_capture_and_learn_action sheds image side-work when degraded."""

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from packages.repeater.message_runtime_handler import build_repeater_capture_and_learn_action

GROUP_ID = 700001


def _event() -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1800000000,
        self_id=10001,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=123,
        user_id=7,
        message=Message([MessageSegment.text("hi"), MessageSegment.image("http://example/x.png")]),
        raw_message="hi [CQ:image,file=http://example/x.png]",
        font=0,
        sender={"user_id": 7, "nickname": "a", "card": "", "role": "member"},
        group_id=GROUP_ID,
    )


def _patch(monkeypatch, *, shed):
    calls: dict[str, list] = {"image": [], "learn": []}

    async def insert_image(*_args, **_kwargs):
        calls["image"].append("image")

    async def enqueue_repeater_learn(*_args, **_kwargs):
        calls["learn"].append("learn")

    monkeypatch.setattr("pallas.core.shared.utils.media_cache.insert_image", insert_image)
    monkeypatch.setattr("packages.repeater.learn_queue.enqueue_repeater_learn", enqueue_repeater_learn)
    monkeypatch.setattr("pallas.core.platform.ingress.message_load.should_shed_chat_sidework", lambda: shed)
    return calls


async def test_image_sidework_runs_when_not_degraded(monkeypatch):
    calls = _patch(monkeypatch, shed=False)
    await build_repeater_capture_and_learn_action(_event(), object()).run()
    assert calls["image"] == ["image"]
    assert calls["learn"] == ["learn"]


async def test_image_sidework_shed_but_message_still_enqueued_when_degraded(monkeypatch):
    calls = _patch(monkeypatch, shed=True)
    await build_repeater_capture_and_learn_action(_event(), object()).run()
    assert calls["image"] == []  # side-work shed
    assert calls["learn"] == ["learn"]  # message persist/learn path still invoked
