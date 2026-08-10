from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.perm import satisfies_command_permission
from pallas.core.platform.message_runtime.models import DeferredAction, HandlingOutcome, MessageContext

from . import service

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


DRINK_COMMANDS = frozenset({"牛牛喝酒", "牛牛干杯", "牛牛继续喝"})
SOBER_UP_COMMANDS = frozenset({"牛牛醒一醒", "牛牛别喝了"})


class DrinkDirectHandler:
    handler_id = "drink.direct"
    modules = frozenset({"drink"})
    passive = False
    fallback_on_error = False

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text.strip() in DRINK_COMMANDS | SOBER_UP_COMMANDS

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        command = context.plain_text.strip()
        if command in DRINK_COMMANDS:
            permission_id = "drink.drink"
            run_service = service.drink
            action_category = "drink"
        elif command in SOBER_UP_COMMANDS:
            permission_id = "drink.sober_up"
            run_service = service.sober_up
            action_category = "sober_up"
        else:
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await satisfies_command_permission(bot, event, permission_id):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)

        async def send(message: str) -> object:
            return await bot.send(event, message)

        async def run() -> None:
            await run_service(event, send)

        return HandlingOutcome(
            handled=True,
            deferred_actions=(
                DeferredAction(
                    name=f"drink_{action_category}_{context.bot_id}_{context.group_id}",
                    run=run,
                    wait_for_completion=True,
                ),
            ),
            continue_matcher=permission_id == "drink.drink",
            matcher_exclude_modules=frozenset({"drink"}) if permission_id == "drink.drink" else frozenset(),
        )
