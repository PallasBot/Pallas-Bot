from __future__ import annotations

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.multi_bot.at_targets import group_at_qq_ids, message_at_fleet_bot


def test_group_at_qq_ids_falls_back_to_raw_message(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.at_targets.get_fleet_bot_ids",
        lambda: frozenset({3599334092}),
    )
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=3599334092,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=3023094357,
        group_id=733291779,
        message_id=1,
        message=Message("两个字"),
        raw_message="[at:qq=3599334092] 两个字",
    )
    assert group_at_qq_ids(event) == frozenset({3599334092})
    assert message_at_fleet_bot(event) is True
