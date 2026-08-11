from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, SendAction

from .chat_message import handle_llm_chat

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


class LlmChatDirectHandler:
    handler_id = "llm_chat.message"
    modules = frozenset({"llm_chat"})
    passive = True
    fallback_on_error = False

    def accepts(self, context: MessageContext) -> bool:
        return context.is_to_me

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if (
            not context.plain_text.strip()
            and not getattr(event, "reply", None)
            and not str(event.get_message()).strip()
        ):
            return HandlingOutcome(handled=False, fallback_to_matcher=True, fallback_reason="empty_direct_mention")
        messages: list[object] = []

        async def send_message(message: object) -> None:
            messages.append(message)

        await handle_llm_chat(bot, event, send_message=send_message)
        return HandlingOutcome(handled=True, actions=tuple(SendAction(message) for message in messages))
