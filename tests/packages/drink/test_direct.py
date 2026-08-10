from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.drink.direct import DrinkDirectHandler
from pallas.core.platform.message_runtime.handlers import RuntimeHandlerRegistry
from pallas.core.platform.message_runtime.models import MessageContext, RuntimeMode
from pallas.core.platform.message_runtime.planner import MessagePlanner
from pallas.core.platform.message_runtime.runtime import MessageRuntime


def context(text: str, *, route_modules: frozenset[str] = frozenset({"drink"})) -> MessageContext:
    return MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=text,
        raw_text=text,
        is_to_me=False,
        command_traffic=True,
        route_modules=route_modules,
    )


@pytest.mark.parametrize(
    "text",
    ["牛牛喝酒", "牛牛干杯", "牛牛继续喝", "牛牛醒一醒", "牛牛别喝了", " 牛牛喝酒 "],
)
def test_drink_native_handler_accepts_every_existing_exact_alias(text: str) -> None:
    assert DrinkDirectHandler().accepts(context(text)) is True


@pytest.mark.parametrize("text", ["牛牛喝", "牛牛醒醒", "牛牛干杯呀"])
def test_drink_native_handler_rejects_other_text(text: str) -> None:
    assert DrinkDirectHandler().accepts(context(text)) is False


def test_drink_native_handler_only_owns_drink_route() -> None:
    registry = RuntimeHandlerRegistry()
    registry.register(DrinkDirectHandler())

    assert MessagePlanner(registry).plan(context("牛牛喝酒")).kind == "direct"
    assert MessagePlanner(registry).plan(context("牛牛喝酒", route_modules=frozenset({"greeting"}))).kind == "matcher"


@pytest.mark.asyncio
async def test_shadow_planning_has_no_permission_or_service_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    permission = AsyncMock()
    drink = AsyncMock()
    monkeypatch.setattr("packages.drink.direct.satisfies_command_permission", permission)
    monkeypatch.setattr("packages.drink.direct.service.drink", drink)
    registry = RuntimeHandlerRegistry()
    registry.register(DrinkDirectHandler())
    runtime = MessageRuntime(RuntimeMode.SHADOW, MessagePlanner(registry), registry)

    plan = await runtime.submit(context("牛牛喝酒"))

    assert plan.kind == "direct"
    permission.assert_not_awaited()
    drink.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "permission_id", "service_name"),
    [
        ("牛牛喝酒", "drink.drink", "drink"),
        ("牛牛干杯", "drink.drink", "drink"),
        ("牛牛继续喝", "drink.drink", "drink"),
        ("牛牛醒一醒", "drink.sober_up", "sober_up"),
        ("牛牛别喝了", "drink.sober_up", "sober_up"),
    ],
)
async def test_native_handler_checks_permission_then_defers_shared_service(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    permission_id: str,
    service_name: str,
) -> None:
    permission = AsyncMock(return_value=True)
    drink = AsyncMock()
    sober_up = AsyncMock()
    monkeypatch.setattr("packages.drink.direct.satisfies_command_permission", permission)
    monkeypatch.setattr("packages.drink.direct.service.drink", drink)
    monkeypatch.setattr("packages.drink.direct.service.sober_up", sober_up)
    bot = MagicMock()
    bot.send = AsyncMock()
    event = SimpleNamespace(self_id=1, group_id=2)

    outcome = await DrinkDirectHandler().handle(context(text), bot=bot, event=event)

    permission.assert_awaited_once_with(bot, event, permission_id)
    assert outcome.handled is True
    assert outcome.fallback_to_matcher is False
    assert len(outcome.deferred_actions) == 1
    assert outcome.deferred_actions[0].wait_for_completion is True
    assert outcome.continue_matcher is (permission_id == "drink.drink")
    assert outcome.matcher_exclude_modules == (frozenset({"drink"}) if permission_id == "drink.drink" else frozenset())
    drink.assert_not_awaited()
    sober_up.assert_not_awaited()

    await outcome.deferred_actions[0].run()

    selected = drink if service_name == "drink" else sober_up
    selected.assert_awaited_once()
    send = selected.await_args.args[1]
    await send("reply")
    bot.send.assert_awaited_once_with(event, "reply")


@pytest.mark.asyncio
async def test_denied_permission_falls_back_without_service_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.drink.direct.satisfies_command_permission", AsyncMock(return_value=False))
    drink = AsyncMock()
    monkeypatch.setattr("packages.drink.direct.service.drink", drink)

    outcome = await DrinkDirectHandler().handle(context("牛牛喝酒"), bot=MagicMock(), event=MagicMock())

    assert outcome.handled is False
    assert outcome.fallback_to_matcher is True
    assert outcome.deferred_actions == ()
    drink.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_failure_does_not_turn_into_legacy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.drink.direct.satisfies_command_permission", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "packages.drink.direct.service.drink",
        AsyncMock(side_effect=RuntimeError("failed after start")),
    )
    registry = RuntimeHandlerRegistry()
    registry.register(DrinkDirectHandler())
    runtime = MessageRuntime(RuntimeMode.DIRECT, MessagePlanner(registry), registry)

    outcome = await runtime.execute_and_commit(
        context("牛牛喝酒"),
        bot=MagicMock(),
        event=SimpleNamespace(self_id=1, group_id=2),
    )
    assert outcome.handled is True
    assert outcome.fallback_to_matcher is False
    assert outcome.error_class == "SideEffectCommitError"
