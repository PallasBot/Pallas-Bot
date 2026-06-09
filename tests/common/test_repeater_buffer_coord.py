from __future__ import annotations

import asyncio

import pytest

from src.foundation.db import Message as MessageModel
from src.platform.shard.coord import repeater_buffer as mod
from src.plugins.repeater.message_store import MessageStore
from src.plugins.repeater.model import Chat


@pytest.mark.asyncio
async def test_repeater_buffer_cross_shard_append(fake_coord_redis, monkeypatch) -> None:
    MessageStore._message_dict.clear()
    Chat._recent_topics.clear()

    event = {
        "event_id": "evt1",
        "source_shard_id": 0,
        "msg": {
            "group_id": 100,
            "user_id": 42,
            "bot_id": 300,
            "raw_message": "hello",
            "is_plain_text": True,
            "plain_text": "hello",
            "keywords": "hello",
            "time": 1700000000,
        },
    }

    settings = type("S", (), {"role": "worker", "shard_id": 1, "enabled": True})()
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: settings)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    await mod.ingest_repeater_buffer_event(event)

    msgs = MessageStore._message_dict.get(100) or []
    assert len(msgs) == 1
    assert msgs[0].plain_text == "hello"
    assert list(Chat._recent_topics[100]) == []


def test_publish_skips_without_redis(monkeypatch) -> None:
    monkeypatch.setattr(mod, "publish_repeater_buffer_redis_sync", lambda env: False)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"role": "worker", "shard_id": 0, "enabled": True})(),
    )
    monkeypatch.setattr(
        "src.platform.coord.redis_settings.coord_redis_enabled",
        lambda: False,
    )

    chat = type(
        "Chat",
        (),
        {
            "group_id": 1,
            "user_id": 2,
            "bot_id": 3,
            "raw_message": "hi",
            "plain_text": "hi",
            "is_plain_text": True,
            "keywords": "hi",
            "_keywords_list": ["hi"],
            "time": 99,
        },
    )()
    mod.publish_repeater_buffer_event_sync(chat)


@pytest.mark.asyncio
async def test_repeater_buffer_cross_shard_append_topics(fake_coord_redis, monkeypatch) -> None:
    MessageStore._message_dict.clear()
    Chat._recent_topics.clear()

    event = {
        "event_id": "evt-topics",
        "source_shard_id": 0,
        "msg": {
            "group_id": 200,
            "user_id": 43,
            "bot_id": 301,
            "raw_message": "草",
            "is_plain_text": True,
            "plain_text": "草",
            "keywords": "草",
            "topics": ["草", "热梗"],
            "time": 1700000001,
        },
    }

    settings = type("S", (), {"role": "worker", "shard_id": 1, "enabled": True})()
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: settings)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    await mod.ingest_repeater_buffer_event(event)

    assert list(Chat._recent_topics[200]) == ["草", "热梗"]


def test_repeater_buffer_duplicate_tail_does_not_append_topics() -> None:
    MessageStore._message_dict.clear()
    Chat._recent_topics.clear()
    MessageStore._message_dict[100] = [
        MessageModel.model_construct(
            group_id=100,
            user_id=42,
            bot_id=300,
            raw_message="hello",
            is_plain_text=True,
            plain_text="hello",
            keywords="hello",
            time=1700000000,
        )
    ]
    Chat._recent_topics[100].append("existing")
    msg = {
        "group_id": 100,
        "user_id": 42,
        "bot_id": 300,
        "raw_message": "hello",
        "is_plain_text": True,
        "plain_text": "hello",
        "keywords": "hello",
        "topics": ["new-topic"],
        "time": 1700000000,
    }

    assert asyncio.run(mod.apply_repeater_buffer_message(msg)) is False
    assert list(Chat._recent_topics[100]) == ["existing"]


def test_repeater_buffer_skips_duplicate_tail() -> None:
    MessageStore._message_dict.clear()
    MessageStore._message_dict[100] = [
        MessageModel.model_construct(
            group_id=100,
            user_id=42,
            bot_id=300,
            raw_message="hello",
            is_plain_text=True,
            plain_text="hello",
            keywords="hello",
            time=1700000000,
        )
    ]
    msg = {
        "group_id": 100,
        "user_id": 42,
        "bot_id": 300,
        "raw_message": "hello",
        "is_plain_text": True,
        "plain_text": "hello",
        "keywords": "hello",
        "time": 1700000000,
    }
    assert asyncio.run(mod.apply_repeater_buffer_message(msg)) is False
    assert len(MessageStore._message_dict[100]) == 1


@pytest.mark.asyncio
async def test_schedule_publish_repeater_buffer_does_not_drop_burst(monkeypatch):
    published: list[dict[str, object]] = []

    async def fake_to_thread(fn, *args, **kwargs):
        await asyncio.sleep(0.002)
        return fn(*args, **kwargs)

    def fake_publish(chat):
        published.append({"plain_text": chat.plain_text})

    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "message_payload_from_chat_data", lambda chat: {"plain_text": chat.plain_text})
    monkeypatch.setattr(mod, "publish_repeater_buffer_event_sync", fake_publish)
    monkeypatch.setattr(mod.asyncio, "to_thread", fake_to_thread)

    def make_chat(idx: int):
        return type(
            "Chat",
            (),
            {
                "plain_text": f"m{idx}",
            },
        )()

    total = 700
    for idx in range(total):
        mod.schedule_publish_repeater_buffer(make_chat(idx))

    await asyncio.sleep(0.5)

    assert [item["plain_text"] for item in published] == [f"m{idx}" for idx in range(total)]
