from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_capture_message_for_persist_keeps_live_message_window_and_capture_for_work_serializes_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._message_dict[42].append(
        MessageModel.model_construct(
            group_id=42,
            user_id=10,
            bot_id=100,
            raw_message="上一句",
            is_plain_text=True,
            plain_text="上一句",
            keywords="上一句",
            time=10,
        )
    )
    monkeypatch.setattr("packages.repeater.responder.Responder._repeat_ignore_user_ids", staticmethod(set))
    monkeypatch.setattr(
        "pallas.core.plugin_coord.duel.should_skip_repeater_learn",
        AsyncMock(return_value=False),
    )

    chat = ChatData(group_id=42, user_id=11, bot_id=100, raw_message="这一句", plain_text="这一句", time=20)
    try:
        message_dict = await Learner.capture_message_for_persist(chat)
        assert message_dict is not None
        assert [msg.raw_message for msg in MessageStore._message_dict[42]] == ["上一句", "这一句"]

        payload = await Learner.capture_for_work(chat, asyncio.Lock(), defaultdict(lambda: deque(maxlen=10)))
        assert payload is not None
        assert payload.predecessor is not None
        assert payload.predecessor["raw_message"] == "上一句"
        assert [msg.raw_message for msg in MessageStore._message_dict[42]] == ["上一句", "这一句"]
    finally:
        MessageStore._message_dict.clear()


@pytest.mark.asyncio
async def test_capture_for_work_marks_group_style_dirty_in_message_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData

    monkeypatch.setattr("packages.repeater.responder.Responder._repeat_ignore_user_ids", staticmethod(set))
    monkeypatch.setattr("pallas.core.plugin_coord.duel.should_skip_repeater_learn", AsyncMock(return_value=False))
    monkeypatch.setattr("packages.repeater.learner.group_messages_before", AsyncMock(return_value=[]))
    monkeypatch.setattr("packages.repeater.learner.MessageStore.capture_message", AsyncMock())
    marked: list[int] = []
    monkeypatch.setattr("pallas.product.persona.group_style_refresh.mark_group_style_dirty", marked.append)

    payload = await Learner.capture_for_work(
        ChatData(group_id=42, user_id=11, bot_id=100, raw_message="这一句", plain_text="这一句", time=20),
        asyncio.Lock(),
        defaultdict(lambda: deque(maxlen=10)),
    )

    assert payload is not None
    assert marked == [42]


@pytest.mark.asyncio
async def test_capture_for_work_preserves_forced_repeat_teaching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData

    monkeypatch.setattr("packages.repeater.responder.Responder._repeat_ignore_user_ids", staticmethod(set))
    monkeypatch.setattr("pallas.core.plugin_coord.duel.should_skip_repeater_learn", AsyncMock(return_value=False))
    monkeypatch.setattr("packages.repeater.learner.group_messages_before", AsyncMock(return_value=[]))
    monkeypatch.setattr("packages.repeater.learner.is_forced_repeat_teaching", lambda *_args: True)
    monkeypatch.setattr("packages.repeater.learner.MessageStore.capture_message", AsyncMock())
    taught: list[int] = []
    monkeypatch.setattr("pallas.product.persona.group_style_refresh.mark_group_style_forced_teach", taught.append)

    await Learner.capture_for_work(
        ChatData(group_id=42, user_id=11, bot_id=100, raw_message="这一句", plain_text="这一句", time=20),
        asyncio.Lock(),
        defaultdict(lambda: deque(maxlen=10)),
    )

    assert taught == [42]


@pytest.mark.asyncio
async def test_process_work_payload_uses_captured_predecessor_without_persisting_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater.learner import Learner
    from packages.repeater.work_payload import RepeaterLearnPayload

    payload = RepeaterLearnPayload(
        chat={
            "group_id": 42,
            "user_id": 11,
            "bot_id": 100,
            "raw_message": "这一句",
            "plain_text": "这一句",
            "time": 20,
        },
        predecessor={
            "group_id": 42,
            "user_id": 10,
            "bot_id": 100,
            "raw_message": "上一句",
            "is_plain_text": True,
            "plain_text": "上一句",
            "keywords": "上一句",
            "time": 10,
        },
    )
    context_insert = AsyncMock()
    persist = AsyncMock()
    scheduled = []
    monkeypatch.setattr(Learner, "_context_insert", context_insert)
    monkeypatch.setattr("packages.repeater.learner.MessageStore.persist_message", persist)
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.schedule_auto_save_group_episode",
        lambda **kwargs: scheduled.append(kwargs),
    )

    await Learner.process_work_payload(payload)

    context_insert.assert_awaited_once()
    persist.assert_not_awaited()
    assert scheduled == [{"bot_id": 100, "group_id": 42}]


@pytest.mark.asyncio
async def test_handle_repeater_message_persists_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.work_handler import handle_repeater_message

    persist = AsyncMock()
    monkeypatch.setattr("packages.repeater.message_store.MessageStore.persist_message", persist)

    await handle_repeater_message({
        "message": {
            "group_id": 42,
            "user_id": 11,
            "bot_id": 100,
            "raw_message": "这一句",
            "plain_text": "这一句",
            "time": 20,
        }
    })

    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_captured_live_message_is_not_repersisted_by_local_periodic_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._synced_prefix_counts = {}
    MessageStore._late_save_time = 0
    try:
        await MessageStore.capture_message(
            ChatData(group_id=42, user_id=11, bot_id=100, raw_message="这一句", plain_text="这一句", time=20)
        )
        persist = AsyncMock()
        monkeypatch.setattr("packages.repeater.message_store.message_repo.bulk_insert", persist)

        assert await MessageStore.periodic_sync_if_buffered() is True
        persist.assert_not_awaited()
        assert MessageStore._synced_prefix_counts == {42: 1}
    finally:
        MessageStore._message_dict.clear()
        MessageStore._synced_prefix_counts = {}
        MessageStore._late_save_time = 0
