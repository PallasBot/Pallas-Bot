from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_group_messages_before_returns_empty_without_db_fallback() -> None:
    from packages.repeater import learner_context as mod
    from packages.repeater.message_store import MessageStore

    chat_data = SimpleNamespace(group_id=123, time=100)
    MessageStore._message_dict.clear()

    called = False

    async def fake_find_recent_in_group(*args, **kwargs):
        nonlocal called
        called = True
        return []

    from packages.repeater import message_store as message_store_mod

    original_repo = message_store_mod.message_repo
    message_store_mod.message_repo = SimpleNamespace(find_recent_in_group=fake_find_recent_in_group)
    try:
        got = await mod.group_messages_before(chat_data)
    finally:
        message_store_mod.message_repo = original_repo

    assert got == []
    assert called is False


@pytest.mark.asyncio
async def test_user_message_before_in_group_returns_none_without_db_fallback() -> None:
    from packages.repeater import learner_context as mod

    chat_data = SimpleNamespace(group_id=123, user_id=456, time=100)
    group_msgs = [SimpleNamespace(user_id=789), SimpleNamespace(user_id=999)]

    called = False

    async def fake_find_recent_in_group(*args, **kwargs):
        nonlocal called
        called = True
        return []

    from packages.repeater import message_store as message_store_mod

    original_repo = message_store_mod.message_repo
    message_store_mod.message_repo = SimpleNamespace(find_recent_in_group=fake_find_recent_in_group)
    try:
        got = await mod.user_message_before_in_group(chat_data, group_msgs)
    finally:
        message_store_mod.message_repo = original_repo

    assert got is None
    assert called is False
