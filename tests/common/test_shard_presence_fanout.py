from __future__ import annotations

import asyncio
from types import SimpleNamespace

from packages.repeater import fanout_reply as fanout_mod
from pallas.core.platform.shard import presence as presence_mod
from pallas.core.platform.shard.coord import bot_action as ba_mod


def test_presence_api_exports_cluster_connection_check() -> None:
    from pallas.api.presence import bot_has_cluster_connection

    assert bot_has_cluster_connection is presence_mod.bot_has_cluster_connection


def test_bot_has_cluster_connection_local(monkeypatch):
    monkeypatch.setattr(presence_mod, "bot_has_local_connection", lambda qq: qq == 100)
    monkeypatch.setattr(presence_mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(presence_mod, "get_cluster_online_bot_ids", lambda: frozenset({200}))
    assert presence_mod.bot_has_cluster_connection(100) is True
    assert presence_mod.bot_has_cluster_connection(200) is True
    assert presence_mod.bot_has_cluster_connection(300) is False


def test_invoke_bot_action_skips_offline_remote(monkeypatch):
    monkeypatch.setattr(ba_mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(presence_mod, "bot_has_local_connection", lambda qq: False)
    monkeypatch.setattr(presence_mod, "bot_has_cluster_connection", lambda qq: False)

    async def run() -> None:
        ok, result = await ba_mod.invoke_bot_action("send_group_msg", 2868075548, {"group_id": 1})
        assert ok is False
        assert result is None

    asyncio.run(run())


def test_list_fanout_bot_ids_filters_offline(monkeypatch):
    fanout_mod._FANOUT_BOT_IDS_CACHE.clear()

    async def fake_list(group_id: int) -> list[int]:
        return [100, 200, 300]

    monkeypatch.setattr(fanout_mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(presence_mod, "get_cluster_online_bot_ids", lambda: frozenset({100, 200}))
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.group_fleet_probe.list_group_online_bot_ids",
        fake_list,
    )

    async def always_true(bid: int, gid: int) -> bool:
        return True

    monkeypatch.setattr(fanout_mod, "bot_may_repeater_reply", always_true)

    async def run() -> None:
        ids = await fanout_mod.list_fanout_bot_ids(1)
        assert ids == [100, 200]

    asyncio.run(run())


def test_list_fanout_bot_ids_uses_short_ttl_cache(monkeypatch):
    fanout_mod._FANOUT_BOT_IDS_CACHE.clear()
    calls = 0
    now = 100.0

    async def fake_list(group_id: int) -> list[int]:
        nonlocal calls
        calls += 1
        return [100, 200]

    monkeypatch.setattr(fanout_mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(fanout_mod.time, "monotonic", lambda: now)
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.group_fleet_probe.list_group_online_bot_ids",
        fake_list,
    )

    async def always_true(bid: int, gid: int) -> bool:
        return True

    monkeypatch.setattr(fanout_mod, "bot_may_repeater_reply", always_true)

    async def run() -> None:
        first = await fanout_mod.list_fanout_bot_ids(1)
        second = await fanout_mod.list_fanout_bot_ids(1)
        assert first == [100, 200]
        assert second == [100, 200]

    asyncio.run(run())
    assert calls == 1


def test_resolve_fanout_gate_uses_single_bot_list_lookup(monkeypatch):
    fanout_mod._FANOUT_BOT_IDS_CACHE.clear()
    calls: list[int] = []

    monkeypatch.setattr(fanout_mod, "repeater_fanout_enabled", lambda: True)

    async def fake_list(group_id: int) -> list[int]:
        calls.append(group_id)
        return [100, 200]

    async def fake_claim(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(fanout_mod, "list_fanout_bot_ids", fake_list)
    monkeypatch.setattr(fanout_mod, "try_claim_group_message_once", fake_claim)

    event = SimpleNamespace(
        group_id=1,
        user_id=2,
        time=3,
        get_plaintext=lambda: "hello",
    )

    async def run() -> None:
        gate = await fanout_mod.resolve_fanout_gate(event)
        assert gate.won is True
        assert gate.bot_ids == (100, 200)

    asyncio.run(run())
    assert calls == [1]


def test_repeater_can_attempt_reply_uses_any_ready_fanout_bot(monkeypatch):
    monkeypatch.setattr(fanout_mod, "repeater_fanout_enabled", lambda: True)
    monkeypatch.setattr(fanout_mod, "list_fanout_bot_ids", lambda _gid: asyncio.sleep(0, result=[100, 200]))

    cooldowns = {100: False, 200: True}

    class _FakeBotConfig:
        def __init__(self, bot_id: int, group_id: int = 0, cooldown: int = 5) -> None:
            self.bot_id = bot_id
            self.group_id = group_id
            self.cooldown = cooldown

        async def is_cooldown(self, action_type: str) -> bool:
            assert action_type == "repeat"
            return cooldowns[self.bot_id]

    monkeypatch.setattr(fanout_mod, "BotConfig", _FakeBotConfig)

    async def run() -> None:
        assert await fanout_mod.repeater_can_attempt_reply(100, 1) is True

    asyncio.run(run())


def test_repeater_can_attempt_reply_rejects_when_no_fanout_bot_ready(monkeypatch):
    monkeypatch.setattr(fanout_mod, "repeater_fanout_enabled", lambda: True)
    monkeypatch.setattr(fanout_mod, "list_fanout_bot_ids", lambda _gid: asyncio.sleep(0, result=[100, 200]))

    class _FakeBotConfig:
        def __init__(self, bot_id: int, group_id: int = 0, cooldown: int = 5) -> None:
            self.bot_id = bot_id
            self.group_id = group_id
            self.cooldown = cooldown

        async def is_cooldown(self, action_type: str) -> bool:
            assert action_type == "repeat"
            return False

    monkeypatch.setattr(fanout_mod, "BotConfig", _FakeBotConfig)

    async def run() -> None:
        assert await fanout_mod.repeater_can_attempt_reply(100, 1) is False

    asyncio.run(run())
