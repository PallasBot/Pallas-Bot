from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from pallas.core.shared.adapters.onebot_v11_custom_events import (
    GroupTempPrivateMessageEvent,
    ProfileLikeNotifyEvent,
    register_onebot_v11_custom_events,
)
from pallas.core.shared.utils.group_temp_context import (
    clear_group_temp_context_for_tests,
    record_user_group_activity,
    resolve_inferred_group_id,
)
from pallas.core.shared.utils.private_send import group_temp_private_group_id


def test_group_temp_private_message_event_parses_payload() -> None:
    payload = {
        "time": 1783961793,
        "self_id": 3841363923,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "group",
        "user_id": 3023094357,
        "group_id": 733291779,
        "message_id": -954833180,
        "message": [{"type": "text", "data": {"text": "牛牛重新上号"}}],
        "raw_message": "牛牛重新上号",
        "font": 0,
        "sender": {"user_id": 3023094357, "nickname": "tester"},
    }
    event = GroupTempPrivateMessageEvent.model_validate(payload)
    assert event.group_id == 733291779
    assert event.sub_type == "group"
    assert group_temp_private_group_id(event) == 733291779


def test_group_temp_private_group_id_ignores_friend_private() -> None:
    payload = {
        "time": 1,
        "self_id": 1,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "user_id": 2,
        "message_id": 1,
        "message": [{"type": "text", "data": {"text": "hi"}}],
        "raw_message": "hi",
        "font": 0,
        "sender": {"user_id": 2, "nickname": "x"},
    }
    from nonebot.adapters.onebot.v11.event import PrivateMessageEvent

    event = PrivateMessageEvent.model_validate(payload)
    assert group_temp_private_group_id(event) is None


def test_profile_like_notify_event_parses_napcat_payload() -> None:
    payload = {
        "time": 1779553477,
        "self_id": 3976691212,
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "profile_like",
        "operator_id": 3791098674,
        "operator_nick": "tester",
        "times": 10,
    }
    event = ProfileLikeNotifyEvent.model_validate(payload)
    assert event.operator_id == 3791098674
    assert event.user_id == 3791098674
    assert event.group_id == 0
    assert event.get_user_id() == "3791098674"


def test_group_temp_private_group_id_reads_sender_group_id() -> None:
    """SnowLuma 把来源群号放在 sender.group_id，而非顶层 group_id。"""
    payload = {
        "time": 1783961793,
        "self_id": 3841363923,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "group",
        "user_id": 3023094357,
        "message_id": -954833180,
        "message": [{"type": "text", "data": {"text": "牛牛重新上号"}}],
        "raw_message": "牛牛重新上号",
        "font": 0,
        "sender": {"user_id": 3023094357, "nickname": "tester", "group_id": 733291779},
    }
    event = GroupTempPrivateMessageEvent.model_validate(payload)
    assert event.group_id == 0
    assert group_temp_private_group_id(event) == 733291779


def test_group_temp_private_group_id_infers_from_recent_group_message() -> None:
    clear_group_temp_context_for_tests()
    record_user_group_activity("3841363923", "3023094357", 733291779)
    payload = {
        "time": 1,
        "self_id": 3841363923,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "group",
        "user_id": 3023094357,
        "message_id": 1,
        "message": [{"type": "text", "data": {"text": "hi"}}],
        "raw_message": "hi",
        "font": 0,
        "sender": {"user_id": 3023094357, "nickname": "x"},
    }
    event = GroupTempPrivateMessageEvent.model_validate(payload)
    assert group_temp_private_group_id(event) == 733291779
    assert resolve_inferred_group_id("3841363923", "3023094357") == 733291779


def test_register_onebot_v11_custom_events() -> None:
    register_onebot_v11_custom_events()
    temp_models = OneBotV11Adapter.get_event_model({
        "post_type": "message",
        "message_type": "private",
        "sub_type": "group",
    })
    assert GroupTempPrivateMessageEvent in temp_models
    like_models = OneBotV11Adapter.get_event_model({
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "profile_like",
    })
    assert ProfileLikeNotifyEvent in like_models
