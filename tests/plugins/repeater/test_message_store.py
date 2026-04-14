"""
Tests for MessageStore class.

Tests message insertion, persistence synchronization, and random message retrieval.
"""

import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_message_insert(beanie_fixture):
    """
    Test that message_insert correctly adds a message to _message_dict.
    """
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    # Setup: Initialize MessageStore state
    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111
        raw_message = "Hello, world!"
        plain_text = "Hello, world!"
        cur_time = 1000

        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message=raw_message,
            plain_text=plain_text,
            time=cur_time,
            bot_id=bot_id,
        )

        # Insert message
        await MessageStore.message_insert(chat_data, topics_callback=None)

        # Verify message was added
        assert group_id in MessageStore._message_dict
        assert len(MessageStore._message_dict[group_id]) == 1

        msg = MessageStore._message_dict[group_id][0]
        assert msg.group_id == group_id
        assert msg.user_id == user_id
        assert msg.bot_id == bot_id
        assert msg.raw_message == raw_message
        assert msg.plain_text == plain_text
        assert msg.time == cur_time

    finally:
        # Cleanup
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_sync_persistence(beanie_fixture):
    """
    Test that sync is triggered and insert_many is called when thresholds are met.
    """
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    # Setup: Initialize MessageStore state
    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 100
    MessageStore.SAVE_COUNT_THRESHOLD = 5
    MessageStore.SAVE_RESERVED_SIZE = 100

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111

        # Mock insert_many to track calls
        with patch("src.plugins.repeater.message_store._message_repo.bulk_insert") as mock_insert:
            mock_insert.return_value = AsyncMock(return_value=None)()

            # Insert messages to exceed count threshold
            for i in range(6):
                chat_data = ChatData(
                    group_id=group_id,
                    user_id=user_id,
                    raw_message=f"Message {i}",
                    plain_text=f"Message {i}",
                    time=200 + i,
                    bot_id=bot_id,
                )
                await MessageStore.message_insert(chat_data, topics_callback=None)

            # Verify insert_many was called
            assert mock_insert.call_count >= 1, "insert_many should be called when count threshold is exceeded"

    finally:
        # Cleanup
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_get_random_message(beanie_fixture):
    """
    Test get_random_message_from_each_group returns one message per group.
    """
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    # Setup: Initialize MessageStore state
    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    try:
        group1_id = 11111
        group2_id = 22222
        user_id = 67890
        bot_id = 11111

        # Insert messages for two groups
        for group_id in [group1_id, group2_id]:
            for i in range(3):
                chat_data = ChatData(
                    group_id=group_id,
                    user_id=user_id,
                    raw_message=f"Message {i} in group {group_id}",
                    plain_text=f"Message {i} in group {group_id}",
                    time=1000 + i,
                    bot_id=bot_id,
                )
                await MessageStore.message_insert(chat_data, topics_callback=None)

        # Get random messages
        result = await MessageStore.get_random_message_from_each_group()

        # Verify result
        assert len(result) == 2, "Should return one message per group"
        assert group1_id in result, "Should include group 1"
        assert group2_id in result, "Should include group 2"
        assert result[group1_id].group_id == group1_id
        assert result[group2_id].group_id == group2_id

    finally:
        # Cleanup
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_topics_callback_called(beanie_fixture):
    """
    Test that topics_callback is called when message is plain text.
    """
    from src.plugins.repeater.message_store import MessageStore
    from src.plugins.repeater.model import ChatData

    # Setup: Initialize MessageStore state
    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111
        raw_message = "Hello world test message"
        plain_text = "Hello world test message"
        cur_time = 1000

        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message=raw_message,
            plain_text=plain_text,
            time=cur_time,
            bot_id=bot_id,
        )

        # Track callback invocations
        callback_invoked = []

        async def mock_callback(gid: int, keywords: list[str]):
            callback_invoked.append((gid, keywords))

        # Insert message with callback
        await MessageStore.message_insert(chat_data, topics_callback=mock_callback)

        # Verify callback was called
        assert len(callback_invoked) == 1, "Callback should be called once for plain text message"
        assert callback_invoked[0][0] == group_id, "Callback should receive correct group_id"
        # Keywords list should be non-empty for this plain text message
        assert isinstance(callback_invoked[0][1], list), "Callback should receive keywords list"

    finally:
        # Cleanup
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0
