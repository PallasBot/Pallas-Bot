from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext

from .handlers.message import handle_group_message

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


class RepeaterNativeHandler:
    handler_id = "repeater.message"
    modules = frozenset({"repeater"})
    passive = True
    fallback_on_error = False

    def accepts(self, context: MessageContext) -> bool:
        return not context.is_to_me

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        await handle_group_message(bot, event)
        return HandlingOutcome(
            handled=True,
            continue_legacy=True,
            legacy_exclude_modules=frozenset({"repeater"}),
        )
