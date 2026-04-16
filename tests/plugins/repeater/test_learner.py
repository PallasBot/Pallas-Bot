"""
Tests for Learner class.

Tests learning logic, context insertion, and filtering (repeat/reply skipping).
"""

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_learn_basic_flow(beanie_fixture):
    """
    Test that learn() inserts message and calls context_insert for previous message.
    """
    from src.common.db import Message as MessageModel
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    # Setup: Initialize MessageStore state
    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111

        # Pre-populate message_dict with a previous message
        prev_msg = MessageModel(
            group_id=group_id,
            user_id=99999,  # Different user
            bot_id=bot_id,
            raw_message="Previous message",
            is_plain_text=True,
            plain_text="Previous message",
            keywords="Previous message",
            time=1000,
        )
        MessageStore._message_dict[group_id].append(prev_msg)

        # Create new chat data
        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message="New message",
            plain_text="New message",
            time=2000,
            bot_id=bot_id,
        )

        with (
            patch(
                "src.plugins.repeater.learner.context_repo.find_by_keywords", new_callable=AsyncMock, return_value=None
            ),
            patch("src.plugins.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

            assert result is True
            assert mock_insert.call_count == 1

    finally:
        # Cleanup
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_learn_empty_message(beanie_fixture):
    """
    Test that learn() returns False for empty messages.
    """
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        chat_data = ChatData(
            group_id=12345,
            user_id=67890,
            raw_message="   ",  # Empty/whitespace only
            plain_text="",
            time=1000,
            bot_id=11111,
        )

        result = await Learner.learn(chat_data, topics_lock, recent_topics)

        # Should skip empty messages
        assert result is False

    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_topics_callback_filters_niuniu_keywords(beanie_fixture):
    """
    Test that _topics_callback filters out keywords starting with '牛牛'
    before updating recent_topics.
    """
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=20))

    try:
        group_id = 12345
        bot_id = 11111

        # Build a plain-text message whose keywords include both normal and "牛牛..." tokens.
        # ChatData.keywords is a space-joined string; _keywords_list splits it back.
        chat_data = ChatData(
            group_id=group_id,
            user_id=67890,
            raw_message="你好 牛牛打架 世界 牛牛你好",
            plain_text="你好 牛牛打架 世界 牛牛你好",
            time=2000,
            bot_id=bot_id,
        )
        # Patch keywords so we control the exact token list
        chat_data._keywords_list = ["你好", "牛牛打架", "世界", "牛牛你好"]

        with (
            patch(
                "src.plugins.repeater.learner.context_repo.find_by_keywords",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("src.plugins.repeater.learner.context_repo.insert", new_callable=AsyncMock),
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

        assert result is True

        topics = list(recent_topics[group_id])
        assert "你好" in topics, "Normal keyword '你好' should be in recent_topics"
        assert "世界" in topics, "Normal keyword '世界' should be in recent_topics"
        assert "牛牛打架" not in topics, "'牛牛打架' starts with '牛牛' and must be filtered out"
        assert "牛牛你好" not in topics, "'牛牛你好' starts with '牛牛' and must be filtered out"

    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_context_insert_skip_repeat(beanie_fixture):
    """
    Test that _context_insert skips when message is a repeat.
    """
    from src.common.db import Message as MessageModel
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.model import ChatData

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="Same message",
        plain_text="Same message",
        time=2000,
        bot_id=11111,
    )

    # Previous message is identical (repeat)
    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Same message",  # Same as current
        is_plain_text=True,
        plain_text="Same message",
        keywords="Same message",
        time=1000,
    )

    with patch("src.plugins.repeater.learner.context_repo.find_by_keywords") as mock_find:
        # Call context_insert
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_find.call_count == 0, "Should skip repeats without querying Context"


@pytest.mark.asyncio
async def test_context_insert_skip_reply(beanie_fixture):
    """
    Test that _context_insert skips when message is a reply.
    """
    from src.common.db import Message as MessageModel
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.model import ChatData

    # Message contains [CQ:reply, tag
    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="[CQ:reply,id=123]Reply message",
        plain_text="Reply message",
        time=2000,
        bot_id=11111,
    )

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Original message",
        is_plain_text=True,
        plain_text="Original message",
        keywords="Original message",
        time=1000,
    )

    with patch("src.plugins.repeater.learner.context_repo.find_by_keywords") as mock_find:
        # Call context_insert
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_find.call_count == 0, "Should skip replies without querying Context"


@pytest.mark.asyncio
async def test_context_insert_skip_none(beanie_fixture):
    """
    Test that _context_insert skips when pre_msg is None.
    """
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.model import ChatData

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="New message",
        plain_text="New message",
        time=2000,
        bot_id=11111,
    )

    with patch("src.plugins.repeater.learner.context_repo.find_by_keywords") as mock_find:
        # Call context_insert with None
        await Learner._context_insert(chat_data, None)

        assert mock_find.call_count == 0, "Should skip None pre_msg without querying Context"


@pytest.mark.asyncio
async def test_context_insert_increment_count(beanie_fixture):
    """
    Test that _context_insert increments count for existing context with matching answer.
    """
    from src.common.db import Answer
    from src.common.db import Message as MessageModel
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.model import ChatData

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="Response message",
        plain_text="Response message",
        time=2000,
        bot_id=11111,
    )

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Trigger message",
        is_plain_text=True,
        plain_text="Trigger message",
        keywords="Trigger message",
        time=1000,
    )

    # Mock existing context with matching answer
    existing_answer = Answer(
        keywords=chat_data.keywords,
        group_id=chat_data.group_id,
        count=5,
        time=1500,
        messages=["Response message"],
    )

    mock_context = MagicMock()
    mock_context.keywords = "Trigger message"
    mock_context.answers = [existing_answer]
    mock_context.time = 1500
    mock_context.trigger_count = 10
    with (
        patch(
            "src.plugins.repeater.learner.context_repo.find_by_keywords",
            new_callable=AsyncMock,
            return_value=mock_context,
        ),
        patch("src.plugins.repeater.learner.context_repo.save", new_callable=AsyncMock) as mock_save,
    ):
        # Call context_insert
        await Learner._context_insert(chat_data, pre_msg)

        # Verify count was incremented
        assert existing_answer.count == 6, "Count should be incremented"
        assert existing_answer.time == 2000, "Time should be updated"

        # Verify context was saved
        assert mock_save.called, "Context should be saved"
        assert mock_context.trigger_count == 11, "Trigger count should be incremented"


@pytest.mark.asyncio
async def test_context_insert_new_answer(beanie_fixture):
    """
    Test that _context_insert adds new answer for existing context without matching answer.
    """
    from src.common.db import Answer
    from src.common.db import Message as MessageModel
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.model import ChatData

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="New response",
        plain_text="New response",
        time=2000,
        bot_id=11111,
    )

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Trigger message",
        is_plain_text=True,
        plain_text="Trigger message",
        keywords="Trigger message",
        time=1000,
    )

    # Mock existing context with different answer
    existing_answer = Answer(
        keywords="Different keywords",
        group_id=12345,
        count=5,
        time=1500,
        messages=["Different response"],
    )

    mock_context = MagicMock()
    mock_context.keywords = "Trigger message"
    mock_context.answers = [existing_answer]
    mock_context.time = 1500
    mock_context.trigger_count = 10
    with (
        patch(
            "src.plugins.repeater.learner.context_repo.find_by_keywords",
            new_callable=AsyncMock,
            return_value=mock_context,
        ),
        patch("src.plugins.repeater.learner.context_repo.save", new_callable=AsyncMock) as mock_save,
    ):
        # Call context_insert
        await Learner._context_insert(chat_data, pre_msg)

        # Verify new answer was appended
        assert len(mock_context.answers) == 2, "Should have 2 answers now"
        new_answer = mock_context.answers[1]
        assert new_answer.keywords == chat_data.keywords
        assert new_answer.group_id == chat_data.group_id
        assert new_answer.count == 1

        # Verify context was saved
        assert mock_save.called, "Context should be saved"


@pytest.mark.asyncio
async def test_learn_user_backtracking(beanie_fixture):
    """
    Test that learn() finds user's previous message within last 3 messages.
    """
    from src.common.db import Message as MessageModel
    from src.plugins.repeater.learner import Learner
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111

        # Pre-populate with messages where user's previous is within last 3
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=99990,  # Different user (oldest)
                bot_id=bot_id,
                raw_message="Very old message",
                is_plain_text=True,
                plain_text="Very old message",
                keywords="Very old message",
                time=900,
            )
        )
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=99991,
                bot_id=bot_id,
                raw_message="Other user 1",
                is_plain_text=True,
                plain_text="Other user 1",
                keywords="Other user 1",
                time=1100,
            )
        )
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=user_id,  # Same user - within backtracking range
                bot_id=bot_id,
                raw_message="User old message",
                is_plain_text=True,
                plain_text="User old message",
                keywords="User old message",
                time=1150,
            )
        )
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=99992,
                bot_id=bot_id,
                raw_message="Other user 2",
                is_plain_text=True,
                plain_text="Other user 2",
                keywords="Other user 2",
                time=1200,
            )
        )

        # Current message from same user
        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message="User new message",
            plain_text="User new message",
            time=2000,
            bot_id=bot_id,
        )

        with (
            patch(
                "src.plugins.repeater.learner.context_repo.find_by_keywords", new_callable=AsyncMock, return_value=None
            ),
            patch("src.plugins.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

            assert result is True
            assert mock_insert.call_count == 2, "Should create context for both group prev and user prev"

    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0
