from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from packages.llm_chat.commands import clear_invocation_allowed


def test_clear_invocation_allowed_at_bot():
    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=2,
        message=Message("clear"),
        raw_message="clear",
        font=0,
        sender={"user_id": 2, "nickname": "u", "card": "", "role": "member"},
        group_id=3,
    )
    object.__setattr__(event, "to_me", True)
    assert clear_invocation_allowed(event) is True


def test_clear_invocation_allowed_llm_tool_dispatch():
    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=-1,
        user_id=2,
        message=Message("clear"),
        raw_message="clear",
        font=0,
        sender={"user_id": 2, "nickname": "llm", "card": "", "role": "member"},
        group_id=3,
    )
    assert clear_invocation_allowed(event) is True
