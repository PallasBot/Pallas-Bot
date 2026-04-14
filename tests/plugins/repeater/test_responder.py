import asyncio
from collections import defaultdict, deque
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest


class _Config:
    def __init__(self, value: int):
        self._value = value

    async def drunkenness(self) -> int:
        return self._value


@pytest.mark.asyncio
async def test_context_find_repeat_detection():
    from src.plugins.repeater.responder import Responder

    group_id = 111
    bot_id = 222
    raw_message = "repeat_me"
    keywords = "repeat_kw"
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message=raw_message,
        keywords=keywords,
        bot_id=bot_id,
        keywords_len=2,
        to_me=False,
        is_image=False,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][bot_id] = [{"reply": "other", "reply_keywords": "other"}]
    message_dict = defaultdict(list)
    message_dict[group_id] = [
        SimpleNamespace(raw_message="x"),
        SimpleNamespace(raw_message=raw_message),
        SimpleNamespace(raw_message=raw_message),
    ]
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "src.plugins.repeater.responder._context_repo.find_by_keywords", new_callable=AsyncMock
        ) as mock_find_one:
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result == ([raw_message], keywords)
            mock_find_one.assert_not_called()
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_returns_none_no_context():
    from src.plugins.repeater.responder import Responder

    group_id = 123
    bot_id = 456
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="hello",
        keywords="hello_kw",
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
    )
    config = _Config(0)
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    recent_topics = defaultdict(lambda: deque(maxlen=16))

    try:
        with patch(
            "src.plugins.repeater.responder._context_repo.find_by_keywords", new_callable=AsyncMock, return_value=None
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result is None
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_context_find_threshold_filtering():
    from src.common.db import Answer, Context
    from src.plugins.repeater.responder import Responder

    group_id = 789
    bot_id = 321
    chat_data = SimpleNamespace(
        group_id=group_id,
        raw_message="ctx_input",
        keywords="ctx_kw",
        bot_id=bot_id,
        keywords_len=1,
        to_me=False,
        is_image=False,
    )
    config = _Config(0)
    low_answer = Answer(keywords="ans_low", group_id=group_id, count=1, time=1, messages=["low_msg"])
    high_answer = Answer(keywords="ans_high", group_id=group_id, count=3, time=1, messages=["high_msg"])
    context = Context(keywords="ctx_kw", time=1, answers=[low_answer, high_answer])
    reply_dict = defaultdict(lambda: defaultdict(list))
    message_dict = defaultdict(list)
    message_dict[group_id] = []
    recent_topics = defaultdict(lambda: deque(maxlen=16))
    recent_topics[group_id] = deque(maxlen=16)

    try:
        with (
            patch(
                "src.plugins.repeater.responder._context_repo.find_by_keywords",
                new_callable=AsyncMock,
                return_value=context,
            ),
            patch(
                "src.plugins.repeater.responder.BanManager.find_ban_keywords",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("src.plugins.repeater.responder.random.choices", side_effect=[[3], [high_answer]]),
            patch("src.plugins.repeater.responder.random.choice", return_value="high_msg"),
            patch("src.plugins.repeater.responder.random.random", return_value=1.0),
        ):
            result = await Responder._context_find(
                cast("Any", chat_data),
                cast("Any", config),
                reply_dict,
                message_dict,
                recent_topics,
            )
            assert result == (["high_msg"], "ans_high")
    finally:
        reply_dict.clear()
        message_dict.clear()
        recent_topics.clear()


@pytest.mark.asyncio
async def test_reply_post_proc_via_responder():
    from src.plugins.repeater.responder import Responder

    group_id = 555
    bot_id = 666
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_lock = asyncio.Lock()
    reply_dict[group_id][bot_id] = [
        {
            "time": 1,
            "pre_raw_message": "a",
            "pre_keywords": "a",
            "reply": "old",
            "reply_keywords": "a",
        }
    ]

    try:
        ok = await Responder.reply_post_proc("old", "new", bot_id, group_id, reply_dict, reply_lock)
        assert ok is True
        assert reply_dict[group_id][bot_id][0]["reply"] == "new"
    finally:
        reply_dict.clear()
