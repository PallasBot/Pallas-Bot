from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from types import SimpleNamespace

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment


def _event() -> GroupMessageEvent:
    return GroupMessageEvent.model_validate({
        "time": 1,
        "self_id": 10,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "user_id": 20,
        "message_id": 30,
        "group_id": 40,
        "message": [
            {"type": "text", "data": {"text": "hello"}},
            {"type": "markdown", "data": {"content": "# original"}},
            {
                "type": "mface",
                "data": {"name": "smile", "emoji_id": "0123456789abcdef0123456789abcdef"},
            },
            {"type": "at", "data": {"qq": "10"}},
            {"type": "reply", "data": {"id": "77"}},
            {"type": "custom.image", "data": {"file": "stored-image", "sub_type": 9}},
        ],
        "raw_message": "hello[CQ:markdown]",
        "font": 0,
        "sender": {"user_id": 20, "nickname": "sender", "card": ""},
    })


def test_original_message_is_used_for_chat_and_persistence() -> None:
    from packages.repeater.model import Chat
    from packages.repeater.work_payload import chat_data_to_dict, chat_data_to_message_dict
    from pallas.core.platform.ingress.message_recorder import build_message

    event = _event()
    original = str(event.original_message)
    event.message.append(MessageSegment("text", {"text": " mutated"}))

    chat_data = Chat(event).chat_data
    bot = SimpleNamespace(self_id=10)

    assert event.get_message() is event.message
    assert "content=# original" in chat_data.raw_message
    assert "emoji_id=0123456789abcdef0123456789abcdef" in chat_data.raw_message
    assert "[CQ:at,qq=10]" in chat_data.raw_message
    assert "[CQ:reply,id=77]" in chat_data.raw_message
    assert "[CQ:custom.image]" in chat_data.raw_message
    assert "stored-image" not in chat_data.raw_message
    assert "mutated" not in chat_data.raw_message
    assert chat_data.reply_to_message_id == 77
    assert chat_data.plain_text == event.get_plaintext()
    assert chat_data_to_dict(chat_data)["raw_message"] == chat_data.raw_message
    assert chat_data_to_message_dict(chat_data)["raw_message"] == chat_data.raw_message
    assert build_message(event, bot).raw_message == original


def test_plain_text_chat_representation_is_unchanged() -> None:
    from packages.repeater.model import Chat

    event = _event()
    plain = Message([MessageSegment("text", {"text": "ordinary text"})])
    event.message = plain
    event.original_message = plain
    event.raw_message = "ordinary text"

    assert Chat(event).chat_data.raw_message == "ordinary text"


@pytest.mark.parametrize(
    ("segment", "replayable"),
    [
        (MessageSegment("markdown", {"content": "# hello, [world] & tail\n第二行"}), True),
        (MessageSegment("markdown", {}), False),
        (MessageSegment("markdown", {"content": " \n\t"}), False),
        (MessageSegment("mface", {"emoji_id": "aBcD" * 8, "key": "k,]&"}), True),
        (MessageSegment("mface", {"name": "smile"}), False),
        (MessageSegment("mface", {"emoji_id": "not-an-emoji-id"}), False),
        (MessageSegment("image", {"file": "image.png"}), True),
        (MessageSegment("image", {"file": "image.png", "emoji_id": "broken"}), False),
        (MessageSegment("custom_extension", {"metadata": "a,]&#"}), True),
    ],
)
def test_replay_validation_keeps_escaped_data_or_rejects_the_whole_message(segment, replayable) -> None:
    from packages.repeater.message_payload import parse_replayable_message
    from pallas.core.platform.ingress.message_payload import event_message_to_cq

    original = Message([MessageSegment.text("ordinary prefix"), segment])
    raw = event_message_to_cq(SimpleNamespace(original_message=original, raw_message="broken raw"))
    parsed = parse_replayable_message(raw)

    if replayable:
        assert parsed == original
    else:
        assert parsed is None


def test_event_message_conversion_keeps_legacy_fallbacks() -> None:
    from pallas.core.platform.ingress.message_payload import event_message_to_cq

    message = Message("ordinary text")
    assert event_message_to_cq(SimpleNamespace(get_message=lambda: message, raw_message="old")) == str(message)
    assert event_message_to_cq(SimpleNamespace(raw_message="legacy raw")) == "legacy raw"


def test_fanout_payload_keeps_structured_original_message() -> None:
    from packages.repeater.fanout_reply import fanout_payload_from_event
    from packages.repeater.responder import ReplyBundle

    event = _event()
    bundle = ReplyBundle(
        answer_list=["reply"],
        answer_keywords="reply",
        message_pool=["reply"],
    )

    payload = fanout_payload_from_event(event, bundle, fanout_bot_ids=[10])

    assert "content=# original" in payload["raw_message"]
    assert "emoji_id=0123456789abcdef0123456789abcdef" in payload["raw_message"]
    assert "file=stored-image" in payload["raw_message"]
    assert payload["fanout_bot_ids"] == [10]


def _answer_state():
    reply_dict = defaultdict(lambda: defaultdict(list))
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    chat_data = SimpleNamespace(
        group_id=40,
        bot_id=10,
        raw_message="trigger",
        keywords="trigger",
        _keywords_list=["trigger"],
    )
    return reply_dict, recent_topics, chat_data


@pytest.mark.asyncio
async def test_answer_from_bundle_skips_bad_items_before_recording_and_keeps_valid_followups(monkeypatch) -> None:
    from packages.repeater.responder import ReplyBundle, Responder

    monkeypatch.setattr("packages.repeater.reply_record_sync.publish_reply_record", lambda *_args: None)
    bad_markdown = "[CQ:markdown]"
    bad_mface = "[CQ:mface,name=smile]"
    answers = [
        bad_markdown,
        "plain answer",
        "[CQ:markdown,content=# saved]",
        bad_mface,
        "[CQ:mface,emoji_id=0123456789abcdef0123456789abcdef]",
        "[CQ:image,file=image.png,url=https://example.test/image.png]",
        "[CQ:custom_extension,id=1]",
    ]
    bundle = ReplyBundle(answer_list=answers, answer_keywords="answer", message_pool=answers)
    reply_dict, recent_topics, chat_data = _answer_state()

    result = await Responder.answer_from_bundle(
        bundle,
        chat_data,
        SimpleNamespace(),
        reply_dict,
        asyncio.Lock(),
        recent_topics,
        asyncio.Lock(),
        plan=(answers, "answer"),
    )

    assert result is not None
    sent = [str(message) async for message in result]
    assert sent == [
        "plain answer",
        "[CQ:markdown,content=# saved]",
        "[CQ:mface,emoji_id=0123456789abcdef0123456789abcdef]",
        "[CQ:image,file=image.png,url=https://example.test/image.png]",
        "[CQ:custom_extension,id=1]",
    ]
    recorded = [record["reply"] for record in reply_dict[40][10]]
    assert bad_markdown not in recorded
    assert bad_mface not in recorded
    assert recorded[1:] == sent


@pytest.mark.asyncio
async def test_answer_from_bundle_with_only_invalid_items_writes_no_reply_record(monkeypatch) -> None:
    from packages.repeater.responder import ReplyBundle, Responder

    monkeypatch.setattr("packages.repeater.reply_record_sync.publish_reply_record", lambda *_args: None)
    answers = ["[CQ:markdown]", "[CQ:mface,name=smile]"]
    bundle = ReplyBundle(answer_list=answers, answer_keywords="answer", message_pool=answers)
    reply_dict, recent_topics, chat_data = _answer_state()

    result = await Responder.answer_from_bundle(
        bundle,
        chat_data,
        SimpleNamespace(),
        reply_dict,
        asyncio.Lock(),
        recent_topics,
        asyncio.Lock(),
        plan=(answers, "answer"),
    )

    assert result is None
    assert not any(records for bots in reply_dict.values() for records in bots.values())
    assert not recent_topics[40]
