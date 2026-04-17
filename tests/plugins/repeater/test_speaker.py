import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock, patch

import pytest


def _build_message(group_id: int, user_id: int, raw_message: str, keywords: str, time_value: int):
    from src.common.db import Message as MessageModel

    return MessageModel(
        group_id=group_id,
        user_id=user_id,
        bot_id=10001,
        raw_message=raw_message,
        is_plain_text=True,
        plain_text=raw_message,
        keywords=keywords,
        time=time_value,
    )


@pytest.mark.asyncio
async def test_speak_returns_none_when_no_group_has_enough_messages(beanie_fixture):
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.speaker import Speaker

    MessageStore._message_dict = defaultdict(list)
    Speaker._recent_speak = defaultdict(lambda: deque(maxlen=Speaker.DUPLICATE_REPLY))

    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    topics_lock = asyncio.Lock()

    group_id = 30001
    MessageStore._message_dict[group_id] = [_build_message(group_id, 20001, f"m{i}", f"k{i}", i + 1) for i in range(9)]
    reply_dict[group_id][10001] = [{"time": 1, "reply": "x", "reply_keywords": "x"}]

    try:
        with patch("src.plugins.repeater.speaker.time.time", return_value=10000):
            result = await Speaker.speak(reply_dict, reply_lock, recent_topics, topics_lock)
            assert result is None
    finally:
        MessageStore._message_dict.clear()
        Speaker._recent_speak.clear()
        reply_dict.clear()


@pytest.mark.asyncio
async def test_speak_filters_banned_keywords(beanie_fixture):
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.speaker import Speaker

    MessageStore._message_dict = defaultdict(list)
    Speaker._recent_speak = defaultdict(lambda: deque(maxlen=Speaker.DUPLICATE_REPLY))

    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    topics_lock = asyncio.Lock()

    group_id = 30002
    bot_id = 10001
    msg_list = [_build_message(group_id, 20001 + i, f"牛牛-warmup-{i}", f"warmup-{i}", i + 1) for i in range(8)]
    msg_list.extend([
        _build_message(group_id, 20021, "banned-content", "ban_kw", 9),
        _build_message(group_id, 20022, "allowed-content", "allow_kw", 10),
    ])
    MessageStore._message_dict[group_id] = msg_list

    reply_dict[group_id][bot_id] = [{"time": 1, "reply": "x", "reply_keywords": "x"}]

    try:
        with (
            patch("src.plugins.repeater.speaker.time.time", return_value=10000),
            patch("src.plugins.repeater.speaker.random.choice", return_value=bot_id),
            patch("src.plugins.repeater.speaker.random.random", return_value=1.0),
            patch(
                "src.plugins.repeater.speaker.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value={"ban_kw"},
            ),
            patch("src.plugins.repeater.speaker.BotConfig.taken_name", new_callable=AsyncMock, return_value=-1),
        ):
            result = await Speaker.speak(reply_dict, reply_lock, recent_topics, topics_lock)
            assert result is not None
            _, _, speak_list, _ = result
            assert str(speak_list[0]) == "allowed-content"
    finally:
        MessageStore._message_dict.clear()
        Speaker._recent_speak.clear()
        reply_dict.clear()


@pytest.mark.asyncio
async def test_speak_recent_dedup_avoids_same_message_twice(beanie_fixture):
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.speaker import Speaker

    MessageStore._message_dict = defaultdict(list)
    Speaker._recent_speak = defaultdict(lambda: deque(maxlen=Speaker.DUPLICATE_REPLY))

    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    topics_lock = asyncio.Lock()

    group_id = 30003
    bot_id = 10001
    msg_list = [_build_message(group_id, 21000 + i, f"牛牛-warmup-{i}", f"warmup-{i}", i + 1) for i in range(8)]
    msg_list.extend([
        _build_message(group_id, 21021, "dup-a", "dup-a", 9),
        _build_message(group_id, 21022, "dup-b", "dup-b", 10),
    ])
    MessageStore._message_dict[group_id] = msg_list

    reply_dict[group_id][bot_id] = [{"time": 1, "reply": "x", "reply_keywords": "x"}]

    try:
        with (
            patch("src.plugins.repeater.speaker.time.time", return_value=10000),
            patch("src.plugins.repeater.speaker.random.choice", return_value=bot_id),
            patch("src.plugins.repeater.speaker.random.random", return_value=1.0),
            patch(
                "src.plugins.repeater.speaker.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("src.plugins.repeater.speaker.BotConfig.taken_name", new_callable=AsyncMock, return_value=-1),
        ):
            first = await Speaker.speak(reply_dict, reply_lock, recent_topics, topics_lock)
            assert first is not None
            assert str(first[2][0]) == "dup-a"

        for idx, msg in enumerate(MessageStore._message_dict[group_id], start=20001):
            msg.time = idx

        with (
            patch("src.plugins.repeater.speaker.time.time", return_value=30000),
            patch("src.plugins.repeater.speaker.random.choice", return_value=bot_id),
            patch("src.plugins.repeater.speaker.random.random", return_value=1.0),
            patch(
                "src.plugins.repeater.speaker.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("src.plugins.repeater.speaker.BotConfig.taken_name", new_callable=AsyncMock, return_value=-1),
        ):
            second = await Speaker.speak(reply_dict, reply_lock, recent_topics, topics_lock)
            assert second is not None
            assert str(second[2][0]) == "dup-b"
    finally:
        MessageStore._message_dict.clear()
        Speaker._recent_speak.clear()
        reply_dict.clear()
