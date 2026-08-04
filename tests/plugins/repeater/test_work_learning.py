from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_capture_for_work_keeps_live_message_window_and_serializes_predecessor(
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
        payload = await Learner.capture_for_work(chat, asyncio.Lock(), defaultdict(lambda: deque(maxlen=10)))

        assert payload is not None
        assert payload.predecessor is not None
        assert payload.predecessor["raw_message"] == "上一句"
        assert [msg.raw_message for msg in MessageStore._message_dict[42]] == ["上一句", "这一句"]
    finally:
        MessageStore._message_dict.clear()


@pytest.mark.asyncio
async def test_process_work_payload_persists_message_and_uses_captured_predecessor(
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
    monkeypatch.setattr(Learner, "_context_insert", context_insert)
    monkeypatch.setattr("packages.repeater.learner.MessageStore.persist_message", persist)
    marked: list[int] = []
    monkeypatch.setattr("pallas.product.persona.group_style_refresh.mark_group_style_dirty", marked.append)

    await Learner.process_work_payload(payload)

    context_insert.assert_awaited_once()
    persist.assert_awaited_once()
    assert marked == [42]
