from __future__ import annotations

from pallas.api.runtime import (
    DirectCommandContext,
    DirectCommandResult,
    completion_effect,
    matcher_fallback,
    register_exact_command_handler,
)

from . import game, service
from .game import bot_is_group_admin, can_roulette_start, parse_roulette_start_command

MODE_COMMANDS = ("牛牛轮盘踢人", "牛牛踢人轮盘", "牛牛轮盘禁言", "牛牛禁言轮盘")
DRINK_COMMANDS = ("牛牛喝酒", "牛牛干杯", "牛牛继续喝")


async def start(context: DirectCommandContext) -> DirectCommandResult:
    matched, mode = parse_roulette_start_command(context.command_text)
    if not matched or not can_roulette_start(context.group_id):
        return matcher_fallback("unavailable")
    if not await bot_is_group_admin(context.bot, context.event, fresh=True):
        return matcher_fallback("bot_not_group_admin")

    async def run() -> None:
        await service.start_roulette(
            context.event,
            lambda message: context.bot.send(context.event, message),
            mode_override=mode,
        )

    return DirectCommandResult(effects=(completion_effect("roulette.start", run),))


async def fire(context: DirectCommandContext) -> DirectCommandResult:
    if game.roulette_status[context.group_id] == 0:
        return matcher_fallback("inactive")
    if not await bot_is_group_admin(context.bot, context.event):
        return matcher_fallback("bot_not_group_admin")

    async def run() -> None:
        await service.fire_roulette(context.event, lambda message: context.bot.send(context.event, message))

    return DirectCommandResult(effects=(completion_effect("roulette.shot", run),))


async def join_drink(context: DirectCommandContext) -> DirectCommandResult:
    if game.roulette_status[context.group_id] == 0:
        return matcher_fallback("inactive")
    if not await bot_is_group_admin(context.bot, context.event):
        return matcher_fallback("bot_not_group_admin")

    async def run() -> None:
        await service.join_active_roulette(context.event)

    return DirectCommandResult(effects=(completion_effect("roulette.join", run),), continue_matcher=True)


START_DECLARATION = register_exact_command_handler(
    handler_id="roulette.start.direct",
    module="roulette",
    commands=("牛牛轮盘",),
    command_id="roulette.start",
    execute=start,
)
MODE_DECLARATION = register_exact_command_handler(
    handler_id="roulette.mode.direct",
    module="roulette",
    commands=MODE_COMMANDS,
    command_id="roulette.mode_switch",
    execute=start,
)
SHOT_DECLARATION = register_exact_command_handler(
    handler_id="roulette.shot.direct",
    module="roulette",
    commands=("牛牛开枪",),
    command_id="roulette.shot",
    execute=fire,
)
DRINK_DECLARATION = register_exact_command_handler(
    handler_id="roulette.join.direct",
    module="roulette",
    commands=DRINK_COMMANDS,
    command_id="roulette.shot",
    execute=join_drink,
    continue_matcher=True,
)
