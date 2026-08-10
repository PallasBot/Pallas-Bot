from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import get_loaded_plugins

from pallas.core.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.core.perm import satisfies_command_permission
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, SendAction

from .console import format_console_hint_text, format_plugins_summary_text
from .status import format_runtime_status_text

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


class StatusDirectHandler:
    handler_id = "pb_core.status"
    modules = frozenset({"pb_core"})

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text.strip() == "#pallas"

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await satisfies_command_permission(bot, event, self.handler_id):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await is_command_cooldown_ready(event, self.handler_id, default_cd_sec=10):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        await refresh_command_cooldown(event, self.handler_id, default_cd_sec=10)
        return HandlingOutcome(
            handled=True,
            actions=(SendAction(message=format_runtime_status_text(self_id=context.bot_id)),),
        )


class ConsoleDirectHandler:
    handler_id = "pb_core.console"
    modules = frozenset({"pb_core"})

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text.strip() == "牛牛控制台"

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await satisfies_command_permission(bot, event, self.handler_id):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await is_command_cooldown_ready(event, self.handler_id, default_cd_sec=10):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        await refresh_command_cooldown(event, self.handler_id, default_cd_sec=10)
        return HandlingOutcome(handled=True, actions=(SendAction(message=format_console_hint_text()),))


class PluginsDirectHandler:
    handler_id = "pb_core.plugins"
    modules = frozenset({"pb_core"})

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text.strip() == "牛牛插件"

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await satisfies_command_permission(bot, event, self.handler_id):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        if not await is_command_cooldown_ready(event, self.handler_id, default_cd_sec=15):
            return HandlingOutcome(handled=False, fallback_to_matcher=True)
        await refresh_command_cooldown(event, self.handler_id, default_cd_sec=15)
        loaded = {plugin.name for plugin in get_loaded_plugins() if plugin.name}
        return HandlingOutcome(
            handled=True,
            actions=(SendAction(message=format_plugins_summary_text(loaded_names=loaded)),),
        )
