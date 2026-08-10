from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from packages.roulette import game, service


class Event(SimpleNamespace):
    def get_plaintext(self) -> str:
        return self.plain_text


@pytest.fixture(autouse=True)
def reset_game() -> None:
    game.roulette_status.clear()
    game.roulette_count.clear()
    game.roulette_time.clear()
    game.roulette_player.clear(100)
    game.ban_players.clear(100)


@pytest.mark.asyncio
async def test_start_roulette_preserves_dedup_and_state(monkeypatch: pytest.MonkeyPatch) -> None:
    event = Event(self_id=1, group_id=100, user_id=2, time=123, plain_text="牛牛轮盘")
    send = AsyncMock()
    monkeypatch.setattr(service, "try_claim_group_message_once", AsyncMock(return_value=True))
    monkeypatch.setattr(service.random, "randint", lambda _start, _end: 4)
    monkeypatch.setattr(service, "participate_in_roulette_mode", AsyncMock(return_value=False))
    monkeypatch.setattr(service.GroupConfig, "roulette_mode", AsyncMock(return_value=1))

    await service.start_roulette(event, send)

    assert game.roulette_status[100] == 4
    assert game.roulette_count[100] == 0
    assert game.roulette_player.get_user_ids(100) == [2]
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_roulette_does_nothing_when_dedup_claim_is_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    event = Event(self_id=1, group_id=100, user_id=2, time=123, plain_text="牛牛轮盘")
    send = AsyncMock()
    monkeypatch.setattr(service, "try_claim_group_message_once", AsyncMock(return_value=False))

    await service.start_roulette(event, send)

    assert game.roulette_status[100] == 0
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_active_roulette_records_player() -> None:
    event = Event(self_id=1, group_id=100, user_id=2, time=123, plain_text="牛牛喝酒")
    game.roulette_status[100] = 3

    await service.join_active_roulette(event)

    assert game.roulette_player.get_user_ids(100) == [2]
