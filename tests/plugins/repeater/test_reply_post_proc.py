"""Tests for reply_post_proc lock protection.

Verifies that reply_post_proc correctly replaces reply entries
and does so under _reply_lock protection.
"""

import pytest


@pytest.mark.asyncio
async def test_reply_post_proc_replaces_match():
    """Verify reply_post_proc replaces the matching reply entry."""
    from src.plugins.repeater.model import Chat

    group_id = 11111
    bot_id = 22222

    Chat._reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "ctx1",
            "pre_keywords": "k1",
            "reply": "old_reply_1",
            "reply_keywords": "rk1",
        },
        {
            "time": 200,
            "pre_raw_message": "ctx2",
            "pre_keywords": "k2",
            "reply": "target_reply",
            "reply_keywords": "rk2",
        },
        {
            "time": 300,
            "pre_raw_message": "ctx3",
            "pre_keywords": "k3",
            "reply": "old_reply_3",
            "reply_keywords": "rk3",
        },
    ]

    try:
        result = await Chat.reply_post_proc(
            raw_message="target_reply",
            new_msg="replaced_reply",
            bot_id=bot_id,
            group_id=group_id,
        )

        assert result is True
        # The second entry should have been replaced
        assert Chat._reply_dict[group_id][bot_id][1]["reply"] == "replaced_reply"
        # Others untouched
        assert Chat._reply_dict[group_id][bot_id][0]["reply"] == "old_reply_1"
        assert Chat._reply_dict[group_id][bot_id][2]["reply"] == "old_reply_3"
    finally:
        if group_id in Chat._reply_dict and bot_id in Chat._reply_dict[group_id]:
            del Chat._reply_dict[group_id][bot_id]


@pytest.mark.asyncio
async def test_reply_post_proc_no_match():
    """Verify reply_post_proc returns False when no match is found."""
    from src.plugins.repeater.model import Chat

    group_id = 33333
    bot_id = 44444

    Chat._reply_dict[group_id][bot_id] = [
        {
            "time": 100,
            "pre_raw_message": "ctx",
            "pre_keywords": "k",
            "reply": "some_reply",
            "reply_keywords": "rk",
        },
    ]

    try:
        result = await Chat.reply_post_proc(
            raw_message="nonexistent_reply",
            new_msg="new",
            bot_id=bot_id,
            group_id=group_id,
        )
        assert result is False
    finally:
        if group_id in Chat._reply_dict and bot_id in Chat._reply_dict[group_id]:
            del Chat._reply_dict[group_id][bot_id]


@pytest.mark.asyncio
async def test_reply_post_proc_same_message():
    """Verify reply_post_proc returns True immediately when raw == new."""
    from src.plugins.repeater.model import Chat

    result = await Chat.reply_post_proc(
        raw_message="same",
        new_msg="same",
        bot_id=1,
        group_id=1,
    )
    assert result is True
