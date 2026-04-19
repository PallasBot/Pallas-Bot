"""Tests for repeater ban functionality, verifying correct keyword extraction.

This test focuses on the ban() method's keyword extraction logic
by testing the fix where lines 430-431 now correctly use ban_reply
instead of the loop variable reply.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_ban_correct_keywords():
    """
    Verify that ban() extracts keywords from the CORRECT reply (ban_reply),
    not from the loop variable (reply). 通过 append_ban 细粒度 API 的调用参数验证。
    """
    from src.plugins.repeater.model import Chat

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

    ban_raw_message = "hi there 2"
    expected_keywords = "hi_there_2"
    expected_pre_keywords = "hello_key_2"

    try:
        with patch(
            "src.plugins.repeater.ban_manager.context_repo.append_ban",
            new_callable=AsyncMock,
        ) as mock_append:
            result = await Chat.ban(group_id, bot_id, ban_raw_message, "test reason")

        assert result is True
        assert mock_append.call_count == 1
        called_pre_keywords, called_ban = mock_append.call_args.args
        assert called_pre_keywords == expected_pre_keywords
        assert called_ban.keywords == expected_keywords
        assert called_ban.group_id == group_id
        assert called_ban.reason == "test reason"
    finally:
        if group_id in Chat._reply_dict and bot_id in Chat._reply_dict[group_id]:
            del Chat._reply_dict[group_id][bot_id]


@pytest.mark.asyncio
async def test_ban_latest():
    """
    Verify that ban() bans the LATEST reply when ban_raw_message is empty.
    """
    from src.plugins.repeater.model import Chat

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
            "reply_keywords": "keywords3",
        },
    ]

    ban_raw_message = ""

    try:
        with patch(
            "src.plugins.repeater.ban_manager.context_repo.append_ban",
            new_callable=AsyncMock,
        ) as mock_append:
            result = await Chat.ban(group_id, bot_id, ban_raw_message, "test reason")

        assert result is True
        assert mock_append.call_count == 1
        _, called_ban = mock_append.call_args.args
        assert called_ban.keywords == "keywords3"
        assert called_ban.group_id == group_id
    finally:
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
