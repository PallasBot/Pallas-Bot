from __future__ import annotations

from types import SimpleNamespace

from packages.repeater.work_payload import chat_data_to_dict, message_to_dict


def test_work_payload_serialization_removes_nul_characters() -> None:
    chat_data = SimpleNamespace(
        group_id=42,
        user_id=11,
        bot_id=100,
        raw_message="before\x00after",
        plain_text="plain\x00text",
        sender_name="兔\x00兔",
        message_id=21,
        reply_to_message_id=20,
        time=20,
    )
    message = SimpleNamespace(
        group_id=42,
        user_id=12,
        bot_id=100,
        raw_message="previous\x00message",
        plain_text="previous\x00plain",
        time=19,
        is_plain_text=True,
        keywords="key\x00word",
        sender_name="醉\x00湖",
        message_id=19,
        reply_to_message_id=18,
    )

    assert chat_data_to_dict(chat_data)["raw_message"] == "beforeafter"
    assert chat_data_to_dict(chat_data)["plain_text"] == "plaintext"
    assert chat_data_to_dict(chat_data)["sender_name"] == "兔兔"
    assert chat_data_to_dict(chat_data)["message_id"] == 21
    assert chat_data_to_dict(chat_data)["reply_to_message_id"] == 20
    assert message_to_dict(message)["raw_message"] == "previousmessage"
    assert message_to_dict(message)["plain_text"] == "previousplain"
    assert message_to_dict(message)["keywords"] == "keyword"
    assert message_to_dict(message)["sender_name"] == "醉湖"
    assert message_to_dict(message)["message_id"] == 19
    assert message_to_dict(message)["reply_to_message_id"] == 18
