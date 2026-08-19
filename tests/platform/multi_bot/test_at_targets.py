from __future__ import annotations

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.multi_bot.at_targets import group_at_qq_ids, message_at_fleet_bot


def _group_event(*, self_id: int, raw: str, user_id: int = 3023094357, group_id: int = 733291779) -> GroupMessageEvent:
    return GroupMessageEvent.model_construct(
        time=100,
        self_id=self_id,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=user_id,
        group_id=group_id,
        message_id=1,
        message=Message(""),
        raw_message=raw,
    )


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


def test_message_at_fleet_bot_includes_federate_peer_bots(monkeypatch) -> None:
    """被 @ 的牛牛即使不在本部署 fleet，也属于联邦对端，应算作定向点名。"""
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.at_targets.get_fleet_bot_ids",
        lambda: frozenset({2927116873}),
    )
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.at_targets.get_federate_peer_bot_ids",
        lambda: frozenset({3645803250}),
    )
    event = _group_event(self_id=2927116873, raw="[CQ:at,qq=3645803250] 牛牛吃什么")
    assert group_at_qq_ids(event) == frozenset({3645803250})
    assert message_at_fleet_bot(event) is True
