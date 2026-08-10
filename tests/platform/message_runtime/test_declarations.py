from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.api.runtime import (
    DirectCommandResult,
    DirectWorkJob,
    completion_effect,
    register_exact_command_handler,
    reply,
    reset_exact_command_handlers,
)
from pallas.core.platform.message_runtime import declarations as declarations_module
from pallas.core.platform.message_runtime.declarations import build_declaration_handlers
from pallas.core.platform.message_runtime.handlers import RuntimeHandlerRegistry
from pallas.core.platform.message_runtime.models import MessageContext


async def execute(_context):
    raise AssertionError("not executed while building declarations")


def setup_function() -> None:
    reset_exact_command_handlers()


def declaration(handler_id: str, module: str, command: str) -> None:
    register_exact_command_handler(
        handler_id=handler_id,
        module=module,
        commands=(command,),
        command_id=handler_id,
        execute=execute,
    )


def test_snapshot_keeps_valid_handlers_and_reports_duplicate_ids() -> None:
    declaration("roulette.start", "roulette", "牛牛轮盘")
    declaration("roulette.start", "other", "牛牛开枪")

    handlers, diagnostics = build_declaration_handlers()

    assert [handler.handler_id for handler in handlers] == ["roulette.start"]
    assert [(item.code, item.handler_id) for item in diagnostics] == [("duplicate_handler_id", "roulette.start")]


def test_snapshot_rejects_overlapping_ownership_within_one_module() -> None:
    declaration("roulette.start", "roulette", "牛牛轮盘")
    declaration("roulette.mode", "roulette", "牛牛轮盘")

    handlers, diagnostics = build_declaration_handlers()

    assert [handler.handler_id for handler in handlers] == ["roulette.start"]
    assert diagnostics[0].code == "overlapping_command"


def test_independent_modules_can_share_an_exact_command() -> None:
    declaration("drink.direct", "drink", "牛牛喝酒")
    declaration("roulette.join", "roulette", "牛牛喝酒")

    handlers, diagnostics = build_declaration_handlers()
    registry = RuntimeHandlerRegistry()
    for handler in handlers:
        registry.register(handler)
    context = MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="牛牛喝酒",
        raw_text="牛牛喝酒",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"drink", "roulette"}),
    )

    assert diagnostics == ()
    assert registry.handler_ids_for_context(context) == ("drink.direct", "roulette.join")


def test_build_returns_an_immutable_snapshot() -> None:
    declaration("roulette.start", "roulette", "牛牛轮盘")
    handlers, _diagnostics = build_declaration_handlers()
    declaration("roulette.shot", "roulette", "牛牛开枪")

    assert isinstance(handlers, tuple)
    assert [handler.handler_id for handler in handlers] == ["roulette.start"]


@pytest.mark.asyncio
async def test_handler_checks_permission_and_converts_public_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    run = AsyncMock()

    async def execute_result(_context):
        return DirectCommandResult(
            replies=reply("ok").replies,
            work_jobs=(DirectWorkJob(kind="sing.generate", payload={"id": 1}, idempotency_key="sing:1"),),
            effects=(completion_effect("roulette.effect", run),),
            continue_matcher=True,
        )

    monkeypatch.setattr(declarations_module, "satisfies_command_permission", AsyncMock(return_value=True))
    register_exact_command_handler(
        handler_id="roulette.start",
        module="roulette",
        commands=("牛牛轮盘",),
        command_id="roulette.start",
        execute=execute_result,
    )
    handler = build_declaration_handlers()[0][0]
    context = MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="牛牛轮盘",
        raw_text="牛牛轮盘",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"roulette"}),
    )

    outcome = await handler.handle(context, bot=object(), event=object())

    assert outcome.handled is True
    assert outcome.actions[0].message == "ok"
    assert outcome.work_jobs[0].kind == "sing.generate"
    assert outcome.deferred_actions[0].wait_for_completion is True
    assert outcome.continue_matcher is True
    assert outcome.matcher_exclude_modules == frozenset({"roulette"})


@pytest.mark.asyncio
async def test_permission_denial_falls_back_without_invoking_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    execute_callback = AsyncMock()
    monkeypatch.setattr(declarations_module, "satisfies_command_permission", AsyncMock(return_value=False))
    register_exact_command_handler(
        handler_id="roulette.start",
        module="roulette",
        commands=("牛牛轮盘",),
        command_id="roulette.start",
        execute=execute_callback,
    )
    handler = build_declaration_handlers()[0][0]
    context = MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="牛牛轮盘",
        raw_text="牛牛轮盘",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"roulette"}),
    )

    outcome = await handler.handle(context, bot=object(), event=object())

    assert outcome.fallback_to_matcher is True
    execute_callback.assert_not_awaited()
