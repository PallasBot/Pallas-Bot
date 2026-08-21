from __future__ import annotations

import pytest

from pallas.core.platform.multi_bot import group_online_cache as mod


async def test_local_connected_bots_uses_cache(monkeypatch) -> None:
    mod.clear_group_online_cache()
    calls: list[tuple[int, int]] = []

    class FakeBot:
        async def get_group_member_info(self, *, group_id: int, user_id: int):
            calls.append((group_id, user_id))

    monkeypatch.setattr(mod, "get_bots", lambda: {"111": FakeBot(), "222": FakeBot()})

    first = await mod.resolve_local_connected_bots_in_group(626266906)
    second = await mod.resolve_local_connected_bots_in_group(626266906)

    assert first == [111, 222]
    assert second == [111, 222]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_local_connected_bots_prefers_recent_group_event_observations(monkeypatch) -> None:
    mod.clear_group_online_cache()
    mod.remember_local_group_bot(626266906, 111)
    mod.remember_local_group_bot(626266906, 222)

    monkeypatch.setattr(mod, "get_bots", dict)

    assert await mod.resolve_local_connected_bots_in_group(626266906) == [111, 222]


@pytest.mark.asyncio
async def test_local_connected_bots_force_probe_ignores_partial_event_observation(monkeypatch) -> None:
    mod.clear_group_online_cache()
    mod.remember_local_group_bot(626266906, 111)
    calls: list[int] = []

    class FakeBot:
        def __init__(self, bot_id: int) -> None:
            self.bot_id = bot_id

        async def get_group_member_info(self, *, group_id: int, user_id: int):
            assert group_id == 626266906
            assert user_id == self.bot_id
            calls.append(user_id)

    monkeypatch.setattr(mod, "get_bots", lambda: {"111": FakeBot(111), "222": FakeBot(222)})

    assert await mod.resolve_local_connected_bots_in_group(626266906, force_probe=True) == [111, 222]
    assert await mod.resolve_local_connected_bots_in_group(626266906, force_probe=True) == [111, 222]
    assert calls == [111, 222]


@pytest.mark.asyncio
async def test_forget_group_bot_removes_only_target_from_all_group_caches() -> None:
    group_id = 626266906
    mod.clear_group_online_cache()
    mod.remember_local_group_bot(group_id, 111)
    mod.remember_local_group_bot(group_id, 222)
    await mod.store_cached_group_bot_ids(group_id, [111, 222], namespace=mod.NS_FLEET)
    await mod.store_cached_group_bot_ids(group_id, [111, 222], namespace=mod.NS_LOCAL_CONNECTED)

    mod.forget_group_bot(group_id, 111)

    assert mod.recent_local_group_bot_ids(group_id) == [222]
    assert mod.get_cached_group_bot_ids(group_id, namespace=mod.NS_FLEET) == [222]
    assert mod.get_cached_group_bot_ids(group_id, namespace=mod.NS_LOCAL_CONNECTED) == [222]
