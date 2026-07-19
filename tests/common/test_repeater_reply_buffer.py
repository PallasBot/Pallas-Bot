"""repeater_reply_buffer 跨片同步与 ban 多牛匹配。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_should_publish_reply_record_skips_placeholders():
    from packages.repeater.model import Chat
    from packages.repeater.reply_record_sync import should_publish_reply_record

    assert should_publish_reply_record({"reply": "hello", "reply_keywords": "kw"}) is True
    assert should_publish_reply_record({"reply": Chat.REPLY_FLAG, "reply_keywords": Chat.REPLY_FLAG}) is False
    assert should_publish_reply_record({"reply": Chat.SPEAK_FLAG, "reply_keywords": Chat.SPEAK_FLAG}) is False
    assert should_publish_reply_record({"reply": "  ", "reply_keywords": "kw"}) is False
    assert should_publish_reply_record({"reply": "实际发言", "reply_keywords": Chat.SPEAK_FLAG}) is True


def test_publish_reply_record_skips_coord_when_placeholder():
    from packages.repeater.model import Chat
    from packages.repeater.reply_record_sync import publish_reply_record

    with patch(
        "pallas.core.platform.shard.coord.repeater_reply_buffer.schedule_publish_repeater_reply_record",
        MagicMock(),
    ) as mock_schedule:
        with patch("pallas.core.platform.shard.registry.config.is_sharding_active", return_value=True):
            publish_reply_record(1, 2, {"reply": Chat.REPLY_FLAG, "reply_keywords": Chat.REPLY_FLAG})
    mock_schedule.assert_not_called()


@pytest.mark.asyncio
async def test_apply_repeater_reply_record_merges_into_chat_reply_dict():
    from packages.repeater.model import Chat
    from pallas.core.platform.shard.coord.repeater_reply_buffer import apply_repeater_reply_record

    group_id = 90001
    bot_id = 80001
    record = {
        "group_id": group_id,
        "bot_id": bot_id,
        "time": 123,
        "pre_raw_message": "hello",
        "pre_keywords": "hello_kw",
        "reply": "world",
        "reply_keywords": "world_kw",
    }

    try:
        assert await apply_repeater_reply_record(record) is True
        assert Chat._reply_dict[group_id][bot_id][-1]["reply"] == "world"
        assert await apply_repeater_reply_record(record) is False
    finally:
        Chat._reply_dict[group_id].pop(bot_id, None)


@pytest.mark.asyncio
async def test_ingest_repeater_reply_buffer_skips_group_without_local_interest(monkeypatch):
    from packages.repeater.model import Chat
    from pallas.core.platform.shard.coord import repeater_reply_buffer as mod

    Chat._reply_dict.clear()

    event = {
        "event_id": "evt-no-local-interest",
        "source_shard_id": 0,
        "record": {
            "group_id": 90010,
            "bot_id": 80010,
            "time": 123,
            "pre_raw_message": "hello",
            "pre_keywords": "hello_kw",
            "reply": "world",
            "reply_keywords": "world_kw",
        },
    }

    settings = type("S", (), {"role": "worker", "shard_id": 1, "enabled": True})()
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: settings)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.group_fleet_probe.list_local_fleet_bots_in_group",
        lambda _group_id: asyncio.sleep(0, result=[]),
    )

    await mod.ingest_repeater_reply_buffer_event(event)

    assert Chat._reply_dict.get(90010) is None


@pytest.mark.asyncio
async def test_ingest_repeater_reply_buffer_keeps_group_when_local_probe_errors(monkeypatch):
    from packages.repeater.model import Chat
    from pallas.core.platform.shard.coord import repeater_reply_buffer as mod

    Chat._reply_dict.clear()

    event = {
        "event_id": "evt-probe-error",
        "source_shard_id": 0,
        "record": {
            "group_id": 90011,
            "bot_id": 80011,
            "time": 124,
            "pre_raw_message": "hello",
            "pre_keywords": "hello_kw",
            "reply": "world",
            "reply_keywords": "world_kw",
        },
    }

    settings = type("S", (), {"role": "worker", "shard_id": 1, "enabled": True})()
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: settings)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)

    async def _raise(_group_id: int) -> list[int]:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.group_fleet_probe.list_local_fleet_bots_in_group",
        _raise,
    )

    await mod.ingest_repeater_reply_buffer_event(event)

    assert Chat._reply_dict[90011][80011][-1]["reply"] == "world"


@pytest.mark.asyncio
async def test_ban_searches_other_bot_reply_cache():
    from packages.repeater.ban_manager import BanManager

    group_id = 90002
    primary_bot = 80002
    other_bot = 80003
    reply_dict = defaultdict(lambda: defaultdict(list))
    reply_dict[group_id][other_bot] = [
        {
            "time": 100,
            "pre_raw_message": "trigger",
            "pre_keywords": "trigger_kw",
            "reply": "bad line",
            "reply_keywords": "bad_kw",
        }
    ]

    BanManager._blacklist_answer.clear()
    BanManager._blacklist_answer_reserve.clear()

    try:
        with patch(
            "packages.repeater.ban_manager.context_repo.append_ban",
            new_callable=AsyncMock,
        ) as mock_append:
            result = await BanManager.ban(group_id, primary_bot, "bad line", "test", reply_dict)

        assert result is True
        assert mock_append.call_count == 1
        pre_kw, ban_obj = mock_append.call_args.args
        assert pre_kw == "trigger_kw"
        assert ban_obj.keywords == "bad_kw"
    finally:
        BanManager._blacklist_answer.clear()
        BanManager._blacklist_answer_reserve.clear()


@pytest.mark.asyncio
async def test_schedule_publish_repeater_reply_record_does_not_drop_burst(monkeypatch):
    from pallas.core.platform.shard.coord import repeater_reply_buffer as mod

    published: list[dict[str, object]] = []

    async def fake_to_thread(fn, *args, **kwargs):
        await asyncio.sleep(0.002)
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "publish_repeater_reply_record_sync",
        lambda group_id, bot_id, record: published.append({
            "group_id": group_id,
            "bot_id": bot_id,
            **dict(record),
        }),
    )
    monkeypatch.setattr(mod.asyncio, "to_thread", fake_to_thread)

    total = 700
    for idx in range(total):
        mod.schedule_publish_repeater_reply_record(
            1,
            2,
            {
                "time": idx,
                "pre_raw_message": f"q{idx}",
                "pre_keywords": f"qk{idx}",
                "reply": f"a{idx}",
                "reply_keywords": f"ak{idx}",
            },
        )

    await asyncio.sleep(0.5)

    assert [item["reply"] for item in published] == [f"a{idx}" for idx in range(total)]


def test_publish_reply_record_sharding_without_redis_skips_publish(monkeypatch) -> None:
    from pallas.core.platform.shard.coord import repeater_reply_buffer as mod

    monkeypatch.setattr(mod, "publish_repeater_reply_buffer_redis_sync", lambda env: False)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"role": "worker", "shard_id": 0, "enabled": True})(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_settings.coord_redis_enabled",
        lambda: False,
    )

    mod.publish_repeater_reply_record_sync(
        1,
        2,
        {
            "time": 1,
            "pre_raw_message": "q",
            "pre_keywords": "qk",
            "reply": "a",
            "reply_keywords": "ak",
        },
    )
