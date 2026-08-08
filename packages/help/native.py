from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.permission import SUPERUSER

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.core.perm import satisfies_command_permission
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, SendAction

from .config import get_help_config
from .help_args import (
    HELP_COMMAND,
    PLUGIN_DISABLE_ALL_COMMAND,
    PLUGIN_DISABLE_COMMAND,
    PLUGIN_ENABLE_ALL_COMMAND,
    PLUGIN_ENABLE_COMMAND,
    extract_help_tail,
    parse_plugin_toggle_args,
)
from .menu_rows import build_help_menu_rows
from .plugin_manager import find_plugin_by_identifier, get_help_menu_plugins, toggle_plugin
from .renderer import render_plugin_menu_to_image

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


class HelpNativeHandler:
    handler_id = "help.commands"
    modules = frozenset({"help"})

    def accepts(self, context: MessageContext) -> bool:
        text = context.plain_text.strip()
        if matches_command_prefix(text, HELP_COMMAND):
            return not extract_help_tail(text)
        return (
            matches_command_prefix(text, PLUGIN_ENABLE_COMMAND)
            and not matches_command_prefix(text, PLUGIN_ENABLE_ALL_COMMAND)
        ) or (
            matches_command_prefix(text, PLUGIN_DISABLE_COMMAND)
            and not matches_command_prefix(text, PLUGIN_DISABLE_ALL_COMMAND)
        )

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not self.accepts(context):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if matches_command_prefix(context.plain_text, HELP_COMMAND):
            return await self._handle_menu(context, bot=bot, event=event)
        return await self._handle_toggle(context, bot=bot, event=event)

    async def _handle_menu(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not await satisfies_command_permission(bot, event, "help.help"):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if not await is_command_cooldown_ready(event, "help.help"):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        await refresh_command_cooldown(event, "help.help")
        rows = await build_help_menu_rows(
            bot_id=context.bot_id,
            group_id=context.group_id,
            show_ignored=False,
        )
        image_data = await render_plugin_menu_to_image(
            rows,
            show_ignored=False,
            group_id=context.group_id,
            total_plugin_count=len(rows),
            total_enabled_count=sum(1 for row in rows if row.enabled),
        )
        return HandlingOutcome(handled=True, actions=(SendAction(MessageSegment.image(image_data)),))

    async def _handle_toggle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        text = context.plain_text.strip()
        command_id, command, action = self._toggle_command(text)
        if command_id is None:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        if not await satisfies_command_permission(bot, event, command_id):
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        config = get_help_config()
        plugins = get_help_menu_plugins(show_ignored=False, ignored_plugins=config.ignored_plugins)
        args = parse_plugin_toggle_args(text, command, plugin_count=len(plugins))
        if not args:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        plugin_name, error_message = await find_plugin_by_identifier(args[0], config.ignored_plugins)
        if error_message or plugin_name is None:
            return HandlingOutcome(
                handled=True,
                actions=(SendAction(error_message or f"博士，你说的'{args[0]}'是什么呀？"),),
            )
        is_superuser = await SUPERUSER(bot, event)
        _, message = await toggle_plugin(
            plugin_name,
            context.group_id,
            context.bot_id,
            action,
            is_superuser=is_superuser,
        )
        if message is None:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        return HandlingOutcome(handled=True, actions=(SendAction(message),))

    @staticmethod
    def _toggle_command(text: str) -> tuple[str | None, str, str]:
        if matches_command_prefix(text, PLUGIN_ENABLE_COMMAND) and not matches_command_prefix(
            text, PLUGIN_ENABLE_ALL_COMMAND
        ):
            return "help.plugin_enable", PLUGIN_ENABLE_COMMAND, "enable"
        if matches_command_prefix(text, PLUGIN_DISABLE_COMMAND) and not matches_command_prefix(
            text, PLUGIN_DISABLE_ALL_COMMAND
        ):
            return "help.plugin_disable", PLUGIN_DISABLE_COMMAND, "disable"
        return None, "", ""
