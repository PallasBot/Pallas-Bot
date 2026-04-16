"""Tests for repeater ban functionality, verifying correct keyword extraction.

This test focuses on the ban() method's keyword extraction logic
by testing the fix where lines 430-431 now correctly use ban_reply
instead of the loop variable reply.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_ban_correct_keywords():
    """
    Verify that ban() extracts keywords from the CORRECT reply (ban_reply),
    not from the loop variable (reply) which would be the last iterated item.

    This tests the fix for the bug where lines 430-431 used `reply` instead of `ban_reply`.
    """
    # Lazy import to avoid NoneBot initialization in module level
    from src.plugins.repeater.model import Chat

    # Setup: Insert multiple replies with different keywords
    group_id = 12345
    bot_id = 67890

    Chat._reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "hello1",
            "pre_keywords": "hello_key_1",
            "reply": "hi there 1",
            "reply_keywords": "hi_there_1",
        },
        {
            "time": 200,
            "pre_raw_message": "hello2",
            "pre_keywords": "hello_key_2",
            "reply": "hi there 2",
            "reply_keywords": "hi_there_2",
        },
        {
            "time": 300,
            "pre_raw_message": "hello3",
            "pre_keywords": "hello_key_3",
            "reply": "hi there 3",
            "reply_keywords": "hi_there_3",
        },
    ]

    # Ban the second reply (not the last one)
    ban_raw_message = "hi there 2"
    expected_keywords = "hi_there_2"

    mock_context = MagicMock()
    mock_context.ban = []
    mock_context.save = AsyncMock()  # Make save async

    try:
        with patch(
            "src.plugins.repeater.ban_manager._context_repo.find_by_keywords",
            new_callable=AsyncMock,
            return_value=mock_context,
        ):
            result = await Chat.ban(group_id, bot_id, ban_raw_message, "test reason")

        # Verify the ban was successful
        assert result is True

        # Verify the correct keywords were used (from the matched reply, not the loop variable)
        # If bug exists, it would use keywords from the LAST reply (hi_there_3) instead of hi_there_2
        assert len(mock_context.ban) > 0
        assert mock_context.ban[0].keywords == expected_keywords
        assert mock_context.ban[0].group_id == group_id
        assert mock_context.ban[0].reason == "test reason"
        print(f"✓ Correctly used keywords from matched reply: {expected_keywords}")
    finally:
        # Clean up
        if group_id in Chat._reply_dict and bot_id in Chat._reply_dict[group_id]:
            del Chat._reply_dict[group_id][bot_id]


@pytest.mark.asyncio
async def test_ban_latest():
    """
    Verify that ban() bans the LATEST reply when ban_raw_message is empty.
    """
    from src.plugins.repeater.model import Chat

    # Setup: Insert multiple replies
    group_id = 22222
    bot_id = 33333

    Chat._reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "msg1",
            "pre_keywords": "key1",
            "reply": "reply1",
            "reply_keywords": "keywords1",
        },
        {
            "time": 200,
            "pre_raw_message": "msg2",
            "pre_keywords": "key2",
            "reply": "reply2",
            "reply_keywords": "keywords2",
        },
        {
            "time": 300,
            "pre_raw_message": "msg3",
            "pre_keywords": "key3",
            "reply": "reply3",
            "reply_keywords": "keywords3",  # This should be banned
        },
    ]

    # Ban with empty message - should ban the latest reply
    ban_raw_message = ""

    mock_context = MagicMock()
    mock_context.ban = []
    mock_context.save = AsyncMock()  # Make save async

    try:
        with patch(
            "src.plugins.repeater.ban_manager._context_repo.find_by_keywords",
            new_callable=AsyncMock,
            return_value=mock_context,
        ):
            result = await Chat.ban(group_id, bot_id, ban_raw_message, "test reason")

        # Verify the latest reply's keywords were banned
        assert result is True
        assert len(mock_context.ban) > 0
        assert mock_context.ban[0].keywords == "keywords3"
        assert mock_context.ban[0].group_id == group_id
        print("✓ Correctly banned latest reply with keywords: keywords3")
    finally:
        # Clean up
        if group_id in Chat._reply_dict and bot_id in Chat._reply_dict[group_id]:
            del Chat._reply_dict[group_id][bot_id]


@pytest.mark.asyncio
async def test_ban_no_match():
    """
    Verify that ban() returns False when no matching reply is found.
    """
    from src.plugins.repeater.model import Chat

    group_id = 44444
    bot_id = 55555

    Chat._reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "msg",
            "pre_keywords": "key",
            "reply": "reply",
            "reply_keywords": "keywords",
        },
    ]

    try:
        # Try to ban a non-existent message
        ban_raw_message = "non existent message"
        result = await Chat.ban(group_id, bot_id, ban_raw_message, "test reason")

        # Verify ban failed
        assert result is False
        print("✓ Correctly returned False for non-existent message")
    finally:
        # Clean up
        if group_id in Chat._reply_dict and bot_id in Chat._reply_dict[group_id]:
            del Chat._reply_dict[group_id][bot_id]


@pytest.mark.asyncio
async def test_ban_group_not_found():
    """
    Verify that ban() returns False when group_id doesn't exist.
    """
    from src.plugins.repeater.model import Chat

    group_id = 99999  # Non-existent group
    bot_id = 11111

    result = await Chat.ban(group_id, bot_id, "test", "test reason")
    assert result is False
    print("✓ Correctly returned False for non-existent group")
