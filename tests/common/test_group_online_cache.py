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
