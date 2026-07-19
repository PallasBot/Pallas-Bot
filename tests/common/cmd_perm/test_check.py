from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent


@pytest.mark.asyncio
async def test_group_moderator_group_event_skips_bot_admin_queries():
    from pallas.core.perm.check import satisfies_command_permission

    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message("x"),
        raw_message="x",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "admin"},
        group_id=1,
    )
    bot = SimpleNamespace()
    with (
        patch("pallas.core.perm.check.resolved_level", return_value="group_moderator"),
        patch("pallas.core.perm.check.SUPERUSER", new_callable=AsyncMock, return_value=False),
        patch("pallas.core.perm.check.user_is_bot_admin", new_callable=AsyncMock) as bot_admin,
        patch("pallas.core.perm.check.user_is_admin_of_any_bot", new_callable=AsyncMock) as any_bot_admin,
    ):
        assert await satisfies_command_permission(bot, event, "dummy.command") is True
    bot_admin.assert_not_awaited()
    any_bot_admin.assert_not_awaited()


@pytest.mark.asyncio
async def test_staff_group_admin_skips_bot_admin_queries():
    from pallas.core.perm.check import satisfies_command_permission

    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message("x"),
        raw_message="x",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "owner"},
        group_id=1,
    )
    bot = SimpleNamespace()
    with (
        patch("pallas.core.perm.check.resolved_level", return_value="staff"),
        patch("pallas.core.perm.check.SUPERUSER", new_callable=AsyncMock, return_value=False),
        patch("pallas.core.perm.check.user_is_bot_admin", new_callable=AsyncMock) as bot_admin,
        patch("pallas.core.perm.check.user_is_admin_of_any_bot", new_callable=AsyncMock) as any_bot_admin,
    ):
        assert await satisfies_command_permission(bot, event, "dummy.command") is True
    bot_admin.assert_not_awaited()
    any_bot_admin.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_moderator_private_event_still_checks_bot_admin():
    from pallas.core.perm.check import satisfies_command_permission

    event = PrivateMessageEvent(
        time=1,
        self_id=11,
        post_type="message",
        message_type="private",
        sub_type="friend",
        message_id=1,
        user_id=22,
        message=Message("x"),
        raw_message="x",
        font=0,
        sender={"user_id": 22},
    )
    bot = SimpleNamespace()
    with (
        patch("pallas.core.perm.check.resolved_level", return_value="group_moderator"),
        patch("pallas.core.perm.check.SUPERUSER", new_callable=AsyncMock, return_value=False),
        patch("pallas.core.perm.check.user_is_bot_admin", new_callable=AsyncMock, return_value=True) as bot_admin,
        patch("pallas.core.perm.check.user_is_admin_of_any_bot", new_callable=AsyncMock) as any_bot_admin,
    ):
        assert await satisfies_command_permission(bot, event, "dummy.command") is True
    bot_admin.assert_awaited_once()
    any_bot_admin.assert_not_awaited()
