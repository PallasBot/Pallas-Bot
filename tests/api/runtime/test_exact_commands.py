from __future__ import annotations

import asyncio

import pytest

from pallas.api.runtime import (
    DirectCommandContext,
    DirectCommandResult,
    DirectWorkJob,
    completion_effect,
    matcher_fallback,
    register_exact_command_handler,
    reply,
)


async def execute(context: DirectCommandContext) -> DirectCommandResult:
    return reply(context.command_text)


def test_register_exact_command_handler_normalizes_an_immutable_public_declaration() -> None:
    declaration = register_exact_command_handler(
        handler_id="roulette.join",
        module="roulette",
        commands=(" 牛牛喝酒 ", "牛牛干杯"),
        command_id="roulette.join",
        execute=execute,
        continue_matcher=True,
    )

    assert declaration.handler_id == "roulette.join"
    assert declaration.module == "roulette"
    assert declaration.commands == frozenset({"牛牛喝酒", "牛牛干杯"})
    assert declaration.command_id == "roulette.join"
    assert declaration.continue_matcher is True
    assert "pallas.core" not in type(declaration).__module__


def test_public_result_helpers_only_create_supported_effects() -> None:
    async def run() -> None:
        await asyncio.sleep(0)

    result = DirectCommandResult(
        replies=reply("ok").replies,
        work_jobs=(DirectWorkJob(kind="sing.generate", payload={"task": "1"}, idempotency_key="sing:1"),),
        effects=(completion_effect("roulette.shot", run),),
        continue_matcher=True,
    )

    assert result.replies[0].message == "ok"
    assert result.effects[0].wait_for_completion is True
    assert matcher_fallback("inactive").fallback_to_matcher is True


def test_completion_effect_can_defer_execution_without_waiting() -> None:
    async def run() -> None:
        await asyncio.sleep(0)

    effect = completion_effect("roulette.penalty", run, wait_for_completion=False)

    assert effect.wait_for_completion is False


@pytest.mark.parametrize("field", ["handler_id", "module", "command_id"])
def test_registration_rejects_empty_identifiers(field: str) -> None:
    values = {
        "handler_id": "roulette.join",
        "module": "roulette",
        "commands": ("牛牛喝酒",),
        "command_id": "roulette.join",
        "execute": execute,
    }
    values[field] = " "

    with pytest.raises(ValueError, match="required"):
        register_exact_command_handler(**values)


def test_registration_rejects_empty_commands() -> None:
    with pytest.raises(ValueError, match="at least one exact command is required"):
        register_exact_command_handler(
            handler_id="roulette.join",
            module="roulette",
            commands=(),
            command_id="roulette.join",
            execute=execute,
        )
