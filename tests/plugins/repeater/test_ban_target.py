from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message


@pytest.mark.asyncio
async def test_resolve_ban_reply_raw_uses_reply_payload_when_present():
    from packages.repeater import resolve_ban_reply_raw

    message = MagicMock()
    message.__iter__.return_value = [MagicMock(__str__=lambda _: "目标消息")]
    reply = MagicMock()
    reply.message = message
    event = MagicMock()
    event.reply = reply
    event.raw_message = "[reply:id=1][at:qq=2] 不可以"

    bot = MagicMock()

    assert await resolve_ban_reply_raw(bot, event) == "目标消息"


@pytest.mark.asyncio
async def test_resolve_ban_reply_raw_falls_back_to_get_msg_when_reply_missing():
    from packages.repeater import resolve_ban_reply_raw

    event = MagicMock()
    event.reply = None
    event.raw_message = "[reply:id=123456][at:qq=2] 不可以"

    bot = MagicMock()
    bot.get_msg = AsyncMock(return_value={"message": "退群播报内容"})

    assert await resolve_ban_reply_raw(bot, event) == "退群播报内容"
    bot.get_msg.assert_awaited_once_with(message_id=123456)


def _make_group_event(
    *,
    self_id: int = 2927116873,
    body: str = "[reply:id=101092384][at:qq=2927116873] 不可以",
    raw_message: str | None = None,
    to_me: bool = False,
) -> GroupMessageEvent:
    return GroupMessageEvent.model_construct(
        time=1,
        self_id=self_id,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=3023094357,
        group_id=733291779,
        message_id=793696852,
        message=Message(body),
        raw_message=raw_message or body,
        reply=None,
        to_me=to_me,
    )


@pytest.mark.asyncio
async def test_is_ban_reply_trigger_matches_raw_at_self_when_to_me_false():
    from packages.repeater import is_ban_reply_trigger

    event = _make_group_event()

    assert await is_ban_reply_trigger(event) is True


@pytest.mark.asyncio
async def test_is_ban_latest_trigger_matches_raw_at_self_when_to_me_false():
    from packages.repeater import is_ban_latest_trigger

    event = _make_group_event(
        body="不可以发这个",
        raw_message="[at:qq=2927116873] 不可以发这个",
    )

    assert await is_ban_latest_trigger(MagicMock(), event, {}) is True
