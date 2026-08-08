from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.core.perm import satisfies_command_permission
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, SendAction

from .status import format_runtime_status_text

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


class StatusNativeHandler:
    handler_id = "pb_core.status"
    modules = frozenset({"pb_core"})

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if context.plain_text.strip() != "#pallas":
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if not await satisfies_command_permission(bot, event, self.handler_id):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if not await is_command_cooldown_ready(event, self.handler_id, default_cd_sec=10):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        await refresh_command_cooldown(event, self.handler_id, default_cd_sec=10)
        return HandlingOutcome(
            handled=True,
            actions=(SendAction(message=format_runtime_status_text(self_id=context.bot_id)),),
        )
