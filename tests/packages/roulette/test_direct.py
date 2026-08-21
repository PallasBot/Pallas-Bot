from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest

from packages.roulette import direct, game
from packages.roulette import __plugin_meta__
from pallas.api.runtime import DirectCommandContext


def context(command: str) -> DirectCommandContext:
    event = SimpleNamespace(self_id=1, group_id=100, message_id=3, user_id=2, time=123)
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
    assert direct.RESCUE_DECLARATION.prefixes == frozenset({"牛牛救一下"})
    assert direct.RESCUE_DECLARATION.command_id == "roulette.rescue"
    assert direct.JUDGMENT_DECLARATION.prefixes == frozenset({"牛牛补一枪"})
    assert direct.JUDGMENT_DECLARATION.command_id == "roulette.punish"


def test_roulette_declares_group_admin_owner_without_fanout() -> None:
    route = __plugin_meta__.extra["ingress_route"]
    assert route["required_bot_capability"] == "group_admin"
    assert "ingress_fanout" not in __plugin_meta__.extra


@pytest.mark.asyncio
async def test_start_uses_cached_group_admin_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    capability = AsyncMock(return_value=False)
    monkeypatch.setattr(direct, "resolve_group_admin_capability", capability)

    result = await direct.start(context("牛牛轮盘"))

    capability.assert_awaited_once_with(100, 1, bot=ANY)
    assert result.fallback_to_matcher is False
    assert result.effects == ()


@pytest.mark.asyncio
async def test_start_stops_matchers_without_side_effect_when_bot_is_not_group_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct, "bot_is_group_admin", AsyncMock(return_value=False))

    result = await direct.start(context("牛牛轮盘"))

    assert result.fallback_to_matcher is False
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


@pytest.mark.asyncio
async def test_resolve_judgment_defers_handler_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = AsyncMock()
    monkeypatch.setattr(direct, "bot_is_group_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(direct, "try_claim_group_message_once", AsyncMock(return_value=True))
    monkeypatch.setattr(direct.game, "rescue_or_judgment_handler", handler)

    result = await direct.resolve_judgment(context("牛牛救一下"))

    assert result.effects[0].name == "roulette.resolve"
    assert result.fallback_to_matcher is False
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_judgment_falls_back_when_claim_is_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(direct, "bot_is_group_admin", AsyncMock(return_value=True))
    monkeypatch.setattr(direct, "try_claim_group_message_once", AsyncMock(return_value=False))

    result = await direct.resolve_judgment(context("牛牛救一下"))

    assert result.fallback_to_matcher is True
    assert result.fallback_reason == "rescue_claim_lost"
    assert result.effects == ()


@pytest.mark.asyncio
async def test_resolve_judgment_falls_back_without_side_effect_when_bot_is_not_group_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct, "bot_is_group_admin", AsyncMock(return_value=False))

    result = await direct.resolve_judgment(context("牛牛补一枪"))

    assert result.fallback_to_matcher is True
    assert result.effects == ()


@pytest.mark.asyncio
async def test_resolve_judgment_rejects_unknown_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await direct.resolve_judgment(context("牛牛开枪"))

    assert result.fallback_to_matcher is True
    assert result.effects == ()
