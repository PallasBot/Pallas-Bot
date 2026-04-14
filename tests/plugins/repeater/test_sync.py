"""
Tests for _sync() method data loss prevention.

Bug fix: Reorder _sync() so insert_many runs BEFORE dict cleanup.
If insert_many fails, _message_dict data is preserved for next sync attempt.
"""

import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_no_data_loss_on_failure(beanie_fixture):
    """
    Test that data is preserved in _message_dict if insert_many fails.

    When MessageModel.insert_many raises an exception:
    - _message_dict should retain all messages (no truncation)
    - _late_save_time should NOT be updated
    - _sync should log the error and return gracefully
    """
    from src.plugins.repeater.model import Chat

    # Setup: Initialize Chat state
    Chat._message_lock = asyncio.Lock()
    Chat._message_dict = defaultdict(list)
    Chat._late_save_time = 0
    Chat.SAVE_RESERVED_SIZE = 100

    group_id = 12345
    cur_time = 1000

    # Create simple mock message objects with time attribute
    mock_messages = []
    for i in range(10):
        msg = type("Message", (), {"time": 100 + i})()
        mock_messages.append(msg)

    # Populate _message_dict
    async with Chat._message_lock:
        Chat._message_dict[group_id] = mock_messages.copy()

    initial_message_count = len(Chat._message_dict[group_id])
    assert initial_message_count == 10

    # Mock insert_many to raise an exception
    with patch("src.plugins.repeater.model.MessageModel.insert_many") as mock_insert:
        mock_insert.side_effect = Exception("Database connection failed")

        # Call _sync - it should fail gracefully
        await Chat._sync(cur_time=cur_time)

    # Verify data is preserved
    final_message_count = len(Chat._message_dict[group_id])
    assert final_message_count == initial_message_count, (
        f"Data loss detected: initial={initial_message_count}, final={final_message_count}"
    )

    # Verify _late_save_time was NOT updated (still 0)
    assert Chat._late_save_time == 0, (
        f"_late_save_time should not be updated on failure, but got {Chat._late_save_time}"
    )


@pytest.mark.asyncio
async def test_cleanup_after_success(beanie_fixture):
    """
    Test that _message_dict is truncated and _late_save_time is updated after successful insert.

    When MessageModel.insert_many succeeds:
    - _message_dict should be truncated to SAVE_RESERVED_SIZE per group
    - _late_save_time should be updated to cur_time
    """
    from src.plugins.repeater.model import Chat

    # Setup: Initialize Chat state
    Chat._message_lock = asyncio.Lock()
    Chat._message_dict = defaultdict(list)
    Chat._late_save_time = 0
    Chat.SAVE_RESERVED_SIZE = 100

    group_id = 54321
    cur_time = 2000

    # Create mock messages with time attributes
    # Create 150 messages so we have more than SAVE_RESERVED_SIZE
    mock_messages = []
    for i in range(150):
        msg = type("Message", (), {"time": 100 + i})()
        mock_messages.append(msg)

    # Populate _message_dict with all messages
    async with Chat._message_lock:
        Chat._message_dict[group_id] = mock_messages.copy()

    initial_message_count = len(Chat._message_dict[group_id])
    assert initial_message_count == 150, f"Expected 150 messages, got {initial_message_count}"

    # Mock insert_many to succeed
    with patch("src.plugins.repeater.model.MessageModel.insert_many") as mock_insert:
        mock_insert.return_value = AsyncMock(return_value=None)()

        # Call _sync
        await Chat._sync(cur_time=cur_time)

    # Verify truncation happened
    final_message_count = len(Chat._message_dict[group_id])
    assert final_message_count <= Chat.SAVE_RESERVED_SIZE, (
        f"Messages not truncated: got {final_message_count}, max should be {Chat.SAVE_RESERVED_SIZE}"
    )

    # Verify we kept the last 100 messages (if there were more than 100)
    assert final_message_count == Chat.SAVE_RESERVED_SIZE, (
        f"Expected exactly {Chat.SAVE_RESERVED_SIZE} messages after truncation, got {final_message_count}"
    )

    # Verify _late_save_time was updated
    assert Chat._late_save_time == cur_time, f"_late_save_time should be {cur_time}, but got {Chat._late_save_time}"

    # Verify insert_many was called exactly once
    assert mock_insert.call_count == 1, (
        f"insert_many should be called once, but was called {mock_insert.call_count} times"
    )
