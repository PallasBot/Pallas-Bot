from nonebot import on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.rule import Rule
from nonebot.typing import T_State

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.core.perm import permission_for_command

from . import startup as _startup  # noqa: F401
from .config import plugin_config
from .handlers import handle_help_command, handle_plugin_operation
from .help_args import (
    HELP_COMMAND,
    PLUGIN_DISABLE_ALL_COMMAND,
    PLUGIN_DISABLE_COMMAND,
    PLUGIN_ENABLE_ALL_COMMAND,
    PLUGIN_ENABLE_COMMAND,
    parse_plugin_toggle_args,
)
from .plugin_manager import get_help_menu_plugins
from .style_cache import AVAILABLE_STYLES, DEFAULT_STYLE_NAME


def prefix_command_rule(command: str, *, exclude_prefixes: tuple[str, ...] = ()) -> Rule:
    async def match_prefix_command(event: Event, state: T_State) -> bool:
        del state
        try:
            plain = event.get_plaintext()
        except Exception:
            return False
        text = plain or ""
        for excluded in exclude_prefixes:
            if matches_command_prefix(text, excluded):
                return False
        return matches_command_prefix(text, command)

    return Rule(match_prefix_command)


help_cmd = on_message(
    prefix_command_rule(HELP_COMMAND),
    priority=5,
    block=True,
    permission=permission_for_command("help.help"),
)

plugin_enable_all_cmd = on_message(
    prefix_command_rule(PLUGIN_ENABLE_ALL_COMMAND),
    priority=4,
    block=True,
    permission=permission_for_command("help.plugin_enable_all"),
)

plugin_disable_all_cmd = on_message(
    prefix_command_rule(PLUGIN_DISABLE_ALL_COMMAND),
    priority=4,
    block=True,
    permission=permission_for_command("help.plugin_disable_all"),
)

plugin_enable_cmd = on_message(
    prefix_command_rule(PLUGIN_ENABLE_COMMAND, exclude_prefixes=(PLUGIN_ENABLE_ALL_COMMAND,)),
    priority=5,
    block=True,
    permission=permission_for_command("help.plugin_enable"),
)

plugin_disable_cmd = on_message(
    prefix_command_rule(PLUGIN_DISABLE_COMMAND, exclude_prefixes=(PLUGIN_DISABLE_ALL_COMMAND,)),
    priority=5,
    block=True,
    permission=permission_for_command("help.plugin_disable"),
)


@help_cmd.handle()
async def handle_help_cmd(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    if isinstance(event, GroupMessageEvent):
        if not await is_command_cooldown_ready(event, "help.help"):
            await help_cmd.finish()
            return
        await refresh_command_cooldown(event, "help.help")

    await handle_help_command(bot, event, state, plugin_config, AVAILABLE_STYLES, DEFAULT_STYLE_NAME, help_cmd)


def toggle_command_plugin_count() -> int:
    return len(
        get_help_menu_plugins(
            show_ignored=False,
            ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
        )
    )


@plugin_enable_cmd.handle()
async def handle_enable_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    args = parse_plugin_toggle_args(
        event.get_plaintext() or "",
        PLUGIN_ENABLE_COMMAND,
        plugin_count=toggle_command_plugin_count(),
    )
    if not args:
        await plugin_enable_cmd.finish("博士，即使身为大祭司，你不说想要开启什么，我也帮不了你呀")
        return

    state["toggle_args"] = args
    await handle_plugin_operation(bot, event, state, "enable", plugin_enable_cmd)


@plugin_disable_cmd.handle()
async def handle_disable_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    args = parse_plugin_toggle_args(
        event.get_plaintext() or "",
        PLUGIN_DISABLE_COMMAND,
        plugin_count=toggle_command_plugin_count(),
    )
    if not args:
        await plugin_disable_cmd.finish("博士，即使身为大祭司，你不说想要关闭什么，我也帮不了你呀")
        return

    state["toggle_args"] = args
    await handle_plugin_operation(bot, event, state, "disable", plugin_disable_cmd)


async def toggle_all_plugins(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, action: str, matcher):
    from nonebot.permission import SUPERUSER

    from .handlers import get_context_info
    from .plugin_manager import get_help_menu_plugins, toggle_plugin
    from .styles import load_config

    bot_id, group_id = get_context_info(bot, event)
    is_superuser = await SUPERUSER(bot, event)
    cfg = load_config()
    plugins = get_help_menu_plugins(
        show_ignored=False,
        ignored_plugins=cfg.ignored_plugins if cfg else [],
    )

    count = 0
    for plugin in plugins:
        success, _ = await toggle_plugin(plugin.name or "", group_id, bot_id, action=action, is_superuser=is_superuser)
        if success:
            count += 1

    action_name = "启用" if action == "enable" else "停止"
    await matcher.finish(f"在米诺斯女神的允许下，我将{action_name} {count} 个能力")


@plugin_enable_all_cmd.handle()
async def handle_enable_all_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    await toggle_all_plugins(bot, event, "enable", plugin_enable_all_cmd)


@plugin_disable_all_cmd.handle()
async def handle_disable_all_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    await toggle_all_plugins(bot, event, "disable", plugin_disable_all_cmd)
