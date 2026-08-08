from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageSegment

from pallas.core.foundation.config import BotConfig
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, SendAction
from pallas.core.plugin_coord.duel import duel_qte_blocks_greeting_user

from .commands import greeting_plugin_disabled
from .voice import get_random_voice
from .welcome_storage import greeting_voices, operator

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


class CallMeNativeHandler:
    handler_id = "greeting.call_me"
    modules = frozenset({"greeting"})

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if context.raw_text != "牛牛":
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if duel_qte_blocks_greeting_user(context.group_id, int(getattr(event, "user_id", 0) or 0)):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if await greeting_plugin_disabled(context.group_id, context.bot_id, bot=bot, event=event):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)

        config = BotConfig(context.bot_id, context.group_id)
        if not await config.is_cooldown("call_me"):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        await config.refresh_cooldown("call_me")

        file_path = get_random_voice(operator, greeting_voices)
        if file_path is None:
            return HandlingOutcome(handled=True)
        voice_bytes = await asyncio.to_thread(file_path.read_bytes)
        return HandlingOutcome(
            handled=True,
            actions=(SendAction(message=MessageSegment.record(file=voice_bytes)),),
        )
