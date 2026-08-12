from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from packages.roulette import direct, game
from pallas.api.runtime import DirectCommandContext


def context(command: str) -> DirectCommandContext:
    event = SimpleNamespace(self_id=1, group_id=100, message_id=3, user_id=2)
    return DirectCommandContext(
        bot=object(),
        event=event,
        bot_id=1,
        group_id=100,
        message_id=3,
        command_text=command,
    )


def test_direct_declarations_cover_only_safe_exact_commands() -> None:
    assert direct.START_DECLARATION.commands == frozenset({"牛牛轮盘"})
    assert direct.MODE_DECLARATION.commands == frozenset({
        "牛牛轮盘踢人",
        "牛牛踢人轮盘",
        "牛牛轮盘禁言",
        "牛牛禁言轮盘",
    })
    assert direct.SHOT_DECLARATION.commands == frozenset({"牛牛开枪"})
    assert direct.DRINK_DECLARATION.commands == frozenset({"牛牛喝酒", "牛牛干杯", "牛牛继续喝"})
    assert direct.DRINK_DECLARATION.continue_matcher is True


@pytest.mark.asyncio
async def test_start_falls_back_without_side_effect_when_bot_is_not_group_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct, "bot_is_group_admin", AsyncMock(return_value=False))

    result = await direct.start(context("牛牛轮盘"))

    assert result.fallback_to_matcher is True
    assert result.effects == ()


@pytest.mark.asyncio
async def test_drink_falls_back_when_no_game_is_active() -> None:
    game.roulette_status[100] = 0

    result = await direct.join_drink(context("牛牛干杯"))

    assert result.fallback_to_matcher is True
    assert result.effects == ()


@pytest.mark.asyncio
async def test_fire_defers_only_the_roulette_penalty(monkeypatch: pytest.MonkeyPatch) -> None:
    game.roulette_status[100] = 1
    penalty = AsyncMock()
    monkeypatch.setattr(direct, "bot_is_group_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(direct.service, "prepare_fire_roulette", AsyncMock(return_value=penalty))

    result = await direct.fire(context("牛牛开枪"))

    assert result.effects[0].wait_for_completion is False
    penalty.assert_not_awaited()
