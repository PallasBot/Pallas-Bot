"""Tests for BanManager class extracted from Chat.

This test file focuses on testing the BanManager class methods independently.
"""

import pytest
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ban_with_reply_dict():
    """
    Test BanManager.ban() with reply_dict parameter.
    Verify that ban is applied when matching reply is found.
    """
    from src.plugins.repeater.ban_manager import BanManager
    from src.plugins.repeater.model import Context

    # Setup reply_dict
    group_id = 10001
    bot_id = 20001
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "test input",
            "pre_keywords": "test_input_key",
            "reply": "test output",
            "reply_keywords": "test_output_key",
        }
    ]

    # Mock Context.find_one
    mock_context = MagicMock()
    mock_context.ban = []
    mock_context.save = AsyncMock()

    # Clean state before test
    BanManager._blacklist_answer.clear()
    BanManager._blacklist_answer_reserve.clear()

    try:
        with (
            patch.object(Context, "find_one", new_callable=AsyncMock, return_value=mock_context),
            patch.object(Context, "keywords", create=True),
        ):
            result = await BanManager.ban(group_id, bot_id, "test output", "test reason", reply_dict)

        # Verify ban was successful
        assert result is True
        assert len(mock_context.ban) > 0
        assert mock_context.ban[0].keywords == "test_output_key"
        assert mock_context.ban[0].group_id == group_id
        assert mock_context.ban[0].reason == "test reason"

        # Verify reserve blacklist was updated
        assert "test_output_key" in BanManager._blacklist_answer_reserve[group_id]

        print("✓ BanManager.ban() correctly processes reply_dict parameter")
    finally:
        # Cleanup
        BanManager._blacklist_answer.clear()
        BanManager._blacklist_answer_reserve.clear()


@pytest.mark.asyncio
async def test_find_ban_keywords_aggregation():
    """
    Test BanManager.find_ban_keywords() aggregates group-specific and global bans.
    Verify that it correctly combines blacklist from multiple sources.
    """
    from src.plugins.repeater.ban_manager import BanManager
    from src.plugins.repeater.model import Context
    from src.common.db import Ban

    group_id = 10002

    # Clean state
    BanManager._blacklist_answer.clear()
    BanManager._blacklist_answer_reserve.clear()

    try:
        # Setup blacklist data
        BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG] = {"global_ban_1", "global_ban_2"}
        BanManager._blacklist_answer[group_id] = {"group_ban_1", "group_ban_2"}

        # Create a Context with cross-group bans
        mock_context = MagicMock()
        mock_context.ban = [
            Ban(keywords="context_ban_1", group_id=group_id, reason="test", time=1000),
            Ban(keywords="context_ban_2", group_id=99999, reason="test", time=1001),  # different group
            Ban(keywords="context_ban_2", group_id=88888, reason="test", time=1002),  # same keyword, another group
        ]

        # Call find_ban_keywords
        result = await BanManager.find_ban_keywords(context=mock_context, group_id=group_id)

        # Verify result
        assert "global_ban_1" in result
        assert "global_ban_2" in result
        assert "group_ban_1" in result
        assert "group_ban_2" in result
        assert "context_ban_1" in result
        assert "context_ban_2" in result  # Should be included due to cross-group threshold

        print("✓ BanManager.find_ban_keywords() correctly aggregates bans from multiple sources")
    finally:
        # Cleanup
        BanManager._blacklist_answer.clear()
        BanManager._blacklist_answer_reserve.clear()


@pytest.mark.asyncio
async def test_find_ban_keywords_no_context():
    """
    Test BanManager.find_ban_keywords() with None context.
    Should only return global and group-specific bans.
    """
    from src.plugins.repeater.ban_manager import BanManager

    group_id = 10003

    # Clean state
    BanManager._blacklist_answer.clear()

    try:
        # Setup blacklist data
        BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG] = {"global_ban"}
        BanManager._blacklist_answer[group_id] = {"group_ban"}

        # Call with None context
        result = await BanManager.find_ban_keywords(context=None, group_id=group_id)

        # Verify result
        assert "global_ban" in result
        assert "group_ban" in result
        assert len(result) == 2

        print("✓ BanManager.find_ban_keywords() works correctly with None context")
    finally:
        # Cleanup
        BanManager._blacklist_answer.clear()


@pytest.mark.asyncio
async def test_update_global_blacklist():
    """
    Test BanManager.update_global_blacklist() creates global bans when threshold is met.
    Verify that keywords banned in multiple groups become global bans.
    """
    from src.plugins.repeater.ban_manager import BanManager
    from src.common.db.modules import BlackList

    # Clean state
    BanManager._blacklist_answer.clear()
    BanManager._blacklist_answer_reserve.clear()

    try:
        # Setup: Multiple groups with same banned keyword
        BanManager._blacklist_answer[10001] = {"shared_ban", "unique_ban_1"}
        BanManager._blacklist_answer[10002] = {"shared_ban", "unique_ban_2"}

        # Mock _select_blacklist to do nothing (we're testing the aggregation logic)
        with patch.object(BanManager, "_select_blacklist", new_callable=AsyncMock):
            await BanManager.update_global_blacklist()

        # Verify global blacklist was updated
        assert "shared_ban" in BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG]
        assert "unique_ban_1" not in BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG]
        assert "unique_ban_2" not in BanManager._blacklist_answer[BanManager.BLACKLIST_FLAG]

        print("✓ BanManager.update_global_blacklist() correctly creates global bans at threshold")
    finally:
        # Cleanup
        BanManager._blacklist_answer.clear()
        BanManager._blacklist_answer_reserve.clear()


@pytest.mark.asyncio
async def test_ban_second_offense():
    """
    Test that second ban offense moves keyword from reserve to active blacklist.
    """
    from src.plugins.repeater.ban_manager import BanManager
    from src.plugins.repeater.model import Context

    group_id = 10004
    bot_id = 20004
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "test",
            "pre_keywords": "test_key",
            "reply": "bad_reply",
            "reply_keywords": "bad_keywords",
        }
    ]

    # Clean state
    BanManager._blacklist_answer.clear()
    BanManager._blacklist_answer_reserve.clear()

    try:
        # First offense - should go to reserve
        mock_context = MagicMock()
        mock_context.ban = []
        mock_context.save = AsyncMock()

        with (
            patch.object(Context, "find_one", new_callable=AsyncMock, return_value=mock_context),
            patch.object(Context, "keywords", create=True),
        ):
            await BanManager.ban(group_id, bot_id, "bad_reply", "first offense", reply_dict)

        assert "bad_keywords" in BanManager._blacklist_answer_reserve[group_id]
        assert "bad_keywords" not in BanManager._blacklist_answer[group_id]

        # Second offense - should move to active blacklist
        reply_dict[group_id][bot_id].append({
            "time": 200,
            "pre_raw_message": "test2",
            "pre_keywords": "test_key2",
            "reply": "bad_reply_again",
            "reply_keywords": "bad_keywords",  # same keywords
        })

        mock_context2 = MagicMock()
        mock_context2.ban = []
        mock_context2.save = AsyncMock()

        with (
            patch.object(Context, "find_one", new_callable=AsyncMock, return_value=mock_context2),
            patch.object(Context, "keywords", create=True),
        ):
            await BanManager.ban(group_id, bot_id, "bad_reply_again", "second offense", reply_dict)

        assert "bad_keywords" in BanManager._blacklist_answer[group_id]

        print("✓ BanManager.ban() correctly handles second offense escalation")
    finally:
        # Cleanup
        BanManager._blacklist_answer.clear()
        BanManager._blacklist_answer_reserve.clear()


@pytest.mark.asyncio
async def test_select_blacklist():
    """
    Test BanManager._select_blacklist() loads data from database.
    """
    from src.plugins.repeater.ban_manager import BanManager
    from src.common.db.modules import BlackList

    # Clean state
    BanManager._blacklist_answer.clear()
    BanManager._blacklist_answer_reserve.clear()

    try:
        # Mock database data
        mock_blacklist_items = [
            MagicMock(group_id=10001, answers=["ban1", "ban2"], answers_reserve=["reserve1"]),
            MagicMock(group_id=10002, answers=["ban3"], answers_reserve=["reserve2", "reserve3"]),
        ]

        mock_query = MagicMock()
        mock_query.to_list = AsyncMock(return_value=mock_blacklist_items)

        with patch.object(BlackList, "find_all", return_value=mock_query):
            await BanManager._select_blacklist()

        # Verify data was loaded
        assert "ban1" in BanManager._blacklist_answer[10001]
        assert "ban2" in BanManager._blacklist_answer[10001]
        assert "reserve1" in BanManager._blacklist_answer_reserve[10001]
        assert "ban3" in BanManager._blacklist_answer[10002]
        assert "reserve2" in BanManager._blacklist_answer_reserve[10002]
        assert "reserve3" in BanManager._blacklist_answer_reserve[10002]

        print("✓ BanManager._select_blacklist() correctly loads database data")
    finally:
        # Cleanup
        BanManager._blacklist_answer.clear()
        BanManager._blacklist_answer_reserve.clear()
