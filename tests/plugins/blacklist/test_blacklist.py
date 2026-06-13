"""Tests for src.plugins.blacklist (user global ban + event gate)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from nonebot.adapters.onebot.v11 import (
    FriendRequestEvent,
    GroupMessageEvent,
    GroupRecallNoticeEvent,
    Message,
    PrivateMessageEvent,
)
from nonebot.adapters.onebot.v11.message import MessageSegment
from nonebot.exception import IgnoredException

from src.foundation.config import GroupConfig, UserConfig


@pytest.fixture(autouse=True)
async def reset_blacklist_gate_cache():
    from src.plugins.blacklist import reset_group_ban_gate_cache, reset_user_ban_gate_cache

    await reset_user_ban_gate_cache()
    await reset_group_ban_gate_cache()
    yield
    await reset_user_ban_gate_cache()
    await reset_group_ban_gate_cache()


def test_collect_target_qqs_at_plain_and_dedup():
    from src.plugins.blacklist import collect_target_qqs_from_plain_and_message

    msg = Message([MessageSegment.at(10001), MessageSegment.at(10001), MessageSegment.text(" tail 10002 ")])
    got = collect_target_qqs_from_plain_and_message("also 10003 and 10002", msg)
    assert got == [10001, 10003, 10002]


def test_collect_target_qqs_skips_special_at():
    from src.plugins.blacklist import collect_target_qqs_from_plain_and_message

    msg = Message([
        MessageSegment.at("all"),
        MessageSegment.at(0),
        MessageSegment.at("0"),
    ])
    assert collect_target_qqs_from_plain_and_message("", msg) == []


def test_collect_target_qqs_plain_min_digits():
    """Regex requires 5–15 digit QQ (first digit 1–9)."""
    from src.plugins.blacklist import collect_target_qqs_from_plain_and_message

    msg = Message()
    assert collect_target_qqs_from_plain_and_message("id 1234 only", msg) == []
    assert collect_target_qqs_from_plain_and_message("ok 12345 end", msg) == [12345]


def test_collect_target_qqs_not_inside_long_number():
    from src.plugins.blacklist import collect_target_qqs_from_plain_and_message

    msg = Message()
    plain = "x1000010000100001x"
    assert collect_target_qqs_from_plain_and_message(plain, msg) == []


def test_event_actor_group_message_and_recall():
    from src.plugins.blacklist import event_actor_user_id

    gm = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=501,
        message=Message("hi"),
        raw_message="hi",
        font=0,
        sender={"user_id": 501, "nickname": "a", "card": "", "role": "member"},
        group_id=10,
    )
    assert event_actor_user_id(gm) == 501

    gr = GroupRecallNoticeEvent(
        time=1,
        self_id=1,
        post_type="notice",
        notice_type="group_recall",
        user_id=502,
        operator_id=503,
        message_id=9,
        group_id=10,
    )
    assert event_actor_user_id(gr) == 503


@pytest.mark.asyncio
async def test_query_user_ban_status_for_gate_uses_cache(beanie_fixture):
    from src.plugins.blacklist import query_user_ban_status_for_gate

    uid = 880_001
    await UserConfig(uid).ban()
    first = await query_user_ban_status_for_gate(uid)
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock) as mock_ib:
        second = await query_user_ban_status_for_gate(uid)
    assert first is True
    assert second is True
    mock_ib.assert_not_called()


@pytest.mark.asyncio
async def test_query_user_ban_status_for_gate_coalesces_concurrent_same_uid(beanie_fixture):
    import asyncio

    from src.plugins.blacklist import query_user_ban_status_for_gate, reset_user_ban_gate_cache

    uid = 880_010
    calls = 0

    async def counting_ban(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return False

    await reset_user_ban_gate_cache()
    with patch.object(UserConfig, "is_banned", side_effect=counting_ban):
        results = await asyncio.gather(*[query_user_ban_status_for_gate(uid) for _ in range(25)])
    assert all(r is False for r in results)
    assert calls == 1


@pytest.mark.asyncio
async def test_query_user_ban_status_for_gate_timeout_fail_open(beanie_fixture):
    import asyncio

    from src.plugins.blacklist import query_user_ban_status_for_gate

    async def slow_is_banned():
        await asyncio.sleep(1.0)
        return True

    uid = 880_002
    with (
        patch("src.plugins.blacklist._IS_BANNED_DB_TIMEOUT_SEC", 0.05),
        patch.object(UserConfig, "is_banned", side_effect=slow_is_banned),
    ):
        out = await query_user_ban_status_for_gate(uid)
    assert out is False


@pytest.mark.asyncio
async def test_invalidate_user_ban_gate_cache_forces_refetch(beanie_fixture):
    from src.plugins.blacklist import invalidate_user_ban_gate_cache, query_user_ban_status_for_gate

    uid = 880_003
    await UserConfig(uid).ban()
    assert await query_user_ban_status_for_gate(uid) is True
    await UserConfig(uid).unban()
    assert await query_user_ban_status_for_gate(uid) is True
    await invalidate_user_ban_gate_cache(uid)
    assert await query_user_ban_status_for_gate(uid) is False


@pytest.mark.asyncio
async def test_block_skips_non_onebot_event_module():
    from src.plugins.blacklist import block_globally_banned_users

    class OtherEvent:
        user_id = 1

    OtherEvent.__module__ = "some.other.adapter"

    bot = SimpleNamespace(self_id="99")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock) as mock_banned:
        await block_globally_banned_users(bot, OtherEvent())
    mock_banned.assert_not_called()


@pytest.mark.asyncio
async def test_block_skips_bot_self_uid():
    from src.plugins.blacklist import block_globally_banned_users

    class V11Event:
        user_id = 10

    V11Event.__module__ = "nonebot.adapters.onebot.v11.event"

    bot = SimpleNamespace(self_id="10")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock) as mock_banned:
        await block_globally_banned_users(bot, V11Event())
    mock_banned.assert_not_called()


@pytest.mark.asyncio
async def test_block_skips_when_not_banned():
    from src.plugins.blacklist import block_globally_banned_users

    class V11Event:
        user_id = 20

    V11Event.__module__ = "nonebot.adapters.onebot.v11.event"

    bot = SimpleNamespace(self_id="1")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock, return_value=False):
        await block_globally_banned_users(bot, V11Event())


@pytest.mark.asyncio
async def test_block_raises_ignored_for_banned_generic():
    from src.plugins.blacklist import block_globally_banned_users

    class V11Event:
        user_id = 30

    V11Event.__module__ = "nonebot.adapters.onebot.v11.event"

    bot = SimpleNamespace(self_id="1")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock, return_value=True):
        with pytest.raises(IgnoredException):
            await block_globally_banned_users(bot, V11Event())


@pytest.mark.asyncio
async def test_block_friend_request_rejects_then_ignores():
    from src.plugins.blacklist import block_globally_banned_users

    ev = FriendRequestEvent(
        time=1,
        self_id=11,
        post_type="request",
        request_type="friend",
        user_id=22,
        flag="f1",
        comment="",
    )
    bot = SimpleNamespace(self_id="11")
    with (
        patch.object(UserConfig, "is_banned", new_callable=AsyncMock, return_value=True),
        patch.object(ev, "reject", new_callable=AsyncMock) as mock_reject,
    ):
        with pytest.raises(IgnoredException):
            await block_globally_banned_users(bot, ev)
    mock_reject.assert_awaited_once_with(bot)


@pytest.mark.asyncio
async def test_can_manage_superuser():
    from src.plugins.blacklist import can_manage_blacklist

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
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "member"},
        group_id=1,
    )
    bot = SimpleNamespace()
    with patch("src.features.cmd_perm.check.SUPERUSER", new_callable=AsyncMock, return_value=True):
        assert await can_manage_blacklist(bot, event) is True


@pytest.mark.asyncio
async def test_can_manage_group_owner_without_superuser():
    from src.plugins.blacklist import can_manage_blacklist

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
        patch("src.features.cmd_perm.check.SUPERUSER", new_callable=AsyncMock, return_value=False),
        patch("src.features.cmd_perm.check.user_is_bot_admin", new_callable=AsyncMock, return_value=False),
    ):
        assert await can_manage_blacklist(bot, event) is True


@pytest.mark.asyncio
async def test_can_manage_private_requires_bot_admin():
    from src.plugins.blacklist import can_manage_blacklist

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
        patch("src.features.cmd_perm.check.SUPERUSER", new_callable=AsyncMock, return_value=False),
        patch("src.features.cmd_perm.check.user_is_bot_admin", new_callable=AsyncMock, return_value=False),
    ):
        assert await can_manage_blacklist(bot, event) is False


@pytest.mark.asyncio
async def test_handle_blacklist_add_bans_targets(beanie_fixture):
    from src.plugins.blacklist import blacklist_add_cmd, handle_blacklist_add

    target = 91001
    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message(f"牛牛拉黑 {target}"),
        raw_message=f"牛牛拉黑 {target}",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "owner"},
        group_id=1,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(blacklist_add_cmd, "finish", new_callable=AsyncMock) as mock_finish:
        await handle_blacklist_add(bot, event)
    assert await UserConfig(target).is_banned() is False
    assert target in await GroupConfig(1).blocked_user_ids()
    mock_finish.assert_awaited_once()
    assert str(target) in mock_finish.await_args.args[0]
    assert "在这里" in mock_finish.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_blacklist_add_no_targets_prompt(beanie_fixture):
    from src.plugins.blacklist import blacklist_add_cmd, handle_blacklist_add

    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message("牛牛拉黑"),
        raw_message="牛牛拉黑",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "owner"},
        group_id=1,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(blacklist_add_cmd, "finish", new_callable=AsyncMock) as mock_finish:
        await handle_blacklist_add(bot, event)
    mock_finish.assert_awaited_once()
    assert "米诺斯" in mock_finish.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_blacklist_remove_unbans(beanie_fixture):
    from src.plugins.blacklist import blacklist_remove_cmd, handle_blacklist_remove

    target = 92002
    await GroupConfig(1).add_blocked_users([target])
    assert target in await GroupConfig(1).blocked_user_ids()

    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message(f"牛牛解禁 {target}"),
        raw_message=f"牛牛解禁 {target}",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "owner"},
        group_id=1,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(blacklist_remove_cmd, "finish", new_callable=AsyncMock):
        await handle_blacklist_remove(bot, event)
    assert target not in await GroupConfig(1).blocked_user_ids()
    assert await UserConfig(target).is_banned() is False


@pytest.mark.asyncio
async def test_handle_blacklist_add_private_global_bans(beanie_fixture):
    from src.plugins.blacklist import blacklist_add_cmd, handle_blacklist_add

    target = 91003
    event = PrivateMessageEvent(
        time=1,
        self_id=11,
        post_type="message",
        message_type="private",
        sub_type="friend",
        message_id=1,
        user_id=22,
        message=Message(f"牛牛拉黑 {target}"),
        raw_message=f"牛牛拉黑 {target}",
        font=0,
        sender={"user_id": 22},
    )
    bot = SimpleNamespace(self_id="11")
    with patch.object(blacklist_add_cmd, "finish", new_callable=AsyncMock) as mock_finish:
        await handle_blacklist_add(bot, event)
    assert await UserConfig(target).is_banned() is True
    assert target not in await GroupConfig(1).blocked_user_ids()
    assert "全局" in mock_finish.await_args.args[0]


@pytest.mark.asyncio
async def test_block_group_only_does_not_block_friend_request(beanie_fixture):
    from src.plugins.blacklist import block_globally_banned_users

    await GroupConfig(10).add_blocked_users([22])
    ev = FriendRequestEvent(
        time=1,
        self_id=11,
        post_type="request",
        request_type="friend",
        user_id=22,
        flag="f1",
        comment="",
    )
    bot = SimpleNamespace(self_id="11")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock, return_value=False):
        await block_globally_banned_users(bot, ev)


@pytest.mark.asyncio
async def test_block_group_recall_when_operator_group_blocked(beanie_fixture):
    from src.plugins.blacklist import block_globally_banned_users

    await GroupConfig(10).add_blocked_users([503])
    gr = GroupRecallNoticeEvent(
        time=1,
        self_id=1,
        post_type="notice",
        notice_type="group_recall",
        user_id=502,
        operator_id=503,
        message_id=9,
        group_id=10,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock, return_value=False):
        with pytest.raises(IgnoredException):
            await block_globally_banned_users(bot, gr)


@pytest.mark.asyncio
async def test_handle_blacklist_add_group_private(beanie_fixture):
    from src.plugins.blacklist import blacklist_add_group_cmd, handle_blacklist_add_group

    gid = 93001
    event = PrivateMessageEvent(
        time=1,
        self_id=11,
        post_type="message",
        message_type="private",
        sub_type="friend",
        message_id=1,
        user_id=22,
        message=Message(f"牛牛拉黑群 {gid}"),
        raw_message=f"牛牛拉黑群 {gid}",
        font=0,
        sender={"user_id": 22},
    )
    bot = SimpleNamespace(self_id="11")
    with patch.object(blacklist_add_group_cmd, "finish", new_callable=AsyncMock) as mock_finish:
        await handle_blacklist_add_group(bot, event)
    assert await GroupConfig(gid).is_banned() is True
    mock_finish.assert_awaited_once()
    assert str(gid) in mock_finish.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_blacklist_add_group_in_group_defaults_current(beanie_fixture):
    from src.plugins.blacklist import blacklist_add_group_cmd, handle_blacklist_add_group

    gid = 93002
    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message("牛牛拉黑群"),
        raw_message="牛牛拉黑群",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "owner"},
        group_id=gid,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(blacklist_add_group_cmd, "finish", new_callable=AsyncMock):
        await handle_blacklist_add_group(bot, event)
    assert await GroupConfig(gid).is_banned() is True


@pytest.mark.asyncio
async def test_handle_blacklist_remove_group_unbans(beanie_fixture):
    from src.plugins.blacklist import blacklist_remove_group_cmd, handle_blacklist_remove_group

    gid = 93003
    await GroupConfig(gid).ban()
    event = PrivateMessageEvent(
        time=1,
        self_id=11,
        post_type="message",
        message_type="private",
        sub_type="friend",
        message_id=1,
        user_id=22,
        message=Message(f"牛牛解禁群 {gid}"),
        raw_message=f"牛牛解禁群 {gid}",
        font=0,
        sender={"user_id": 22},
    )
    bot = SimpleNamespace(self_id="11")
    with patch.object(blacklist_remove_group_cmd, "finish", new_callable=AsyncMock):
        await handle_blacklist_remove_group(bot, event)
    assert await GroupConfig(gid).is_banned() is False


@pytest.mark.asyncio
async def test_block_drops_message_in_banned_group(beanie_fixture):
    from src.plugins.blacklist import block_globally_banned_users

    gid = 93004
    await GroupConfig(gid).ban()
    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=501,
        message=Message("hi"),
        raw_message="hi",
        font=0,
        sender={"user_id": 501, "nickname": "a", "card": "", "role": "member"},
        group_id=gid,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(UserConfig, "is_banned", new_callable=AsyncMock) as mock_banned:
        with pytest.raises(IgnoredException):
            await block_globally_banned_users(bot, event)
    mock_banned.assert_not_called()


def test_format_id_list_empty_and_truncated():
    from src.plugins.blacklist import format_id_list

    assert format_id_list([], empty_hint="（无）") == "（无）"
    long_ids = list(range(100001, 100001 + 60))
    text = format_id_list(long_ids, empty_hint="（无）")
    assert "… 共 60 个" in text
    assert text.count(",") == 49


@pytest.mark.asyncio
async def test_build_blacklist_view_message_private(beanie_fixture):
    from src.plugins.blacklist import build_blacklist_view_message

    uid = 94001
    gid = 94002
    await UserConfig(uid).ban()
    await GroupConfig(gid).ban()
    text = await build_blacklist_view_message(None)
    assert str(uid) in text
    assert str(gid) in text
    assert "全局用户拉黑" in text
    assert "全局群拉黑" in text


@pytest.mark.asyncio
async def test_build_blacklist_view_message_group(beanie_fixture):
    from src.plugins.blacklist import build_blacklist_view_message

    gid = 94003
    target = 94004
    await GroupConfig(gid).add_blocked_users([target])
    text = await build_blacklist_view_message(gid)
    assert str(target) in text
    assert "本群屏蔽用户" in text
    assert "未被全局群拉黑" in text


@pytest.mark.asyncio
async def test_handle_blacklist_list_group(beanie_fixture):
    from src.plugins.blacklist import blacklist_list_cmd, handle_blacklist_list

    gid = 94005
    target = 94006
    await GroupConfig(gid).add_blocked_users([target])
    event = GroupMessageEvent(
        time=1,
        self_id=1,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=1,
        user_id=100,
        message=Message("牛牛黑名单"),
        raw_message="牛牛黑名单",
        font=0,
        sender={"user_id": 100, "nickname": "a", "card": "", "role": "owner"},
        group_id=gid,
    )
    bot = SimpleNamespace(self_id="1")
    with patch.object(blacklist_list_cmd, "finish", new_callable=AsyncMock) as mock_finish:
        await handle_blacklist_list(bot, event)
    mock_finish.assert_awaited_once()
    assert str(target) in mock_finish.await_args.args[0]
