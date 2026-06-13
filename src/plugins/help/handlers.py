from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State

from .help_args import parse_help_args
from .markdown_generator import (
    HelpMarkdownIssue,
    generate_function_detail_markdown,
    generate_plugin_functions_markdown,
    generate_plugins_markdown,
)
from .plugin_manager import (
    fill_plugin_status,
    find_plugin,
    find_plugin_by_identifier,
    get_help_menu_plugins,
    is_plugin_disabled,
    plugin_display_name,
    toggle_plugin,
)
from .renderer import send_markdown_as_image


def get_context_info(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    bot_id = int(bot.self_id)

    group_id = None
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id

    return bot_id, group_id


def resolved_plugin_display(internal_name: str) -> str:
    p = find_plugin(internal_name)
    return plugin_display_name(p) if p else internal_name


async def handle_help_command(
    bot: Bot,
    event: GroupMessageEvent | PrivateMessageEvent,
    state: T_State,
    plugin_config,
    available_styles: dict,
    default_style_name: str,
    matcher,
):
    """统一处理帮助命令，支持群聊和私聊"""

    bot_id, group_id = get_context_info(bot, event)
    style_name = default_style_name

    is_superuser = await SUPERUSER(bot, event)
    is_private = isinstance(event, PrivateMessageEvent)
    show_ignored = is_superuser and is_private

    menu_plugins = get_help_menu_plugins(
        show_ignored=show_ignored,
        ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
    )
    args = parse_help_args(event.get_plaintext() or "", plugin_count=len(menu_plugins))

    if len(args) == 0:
        markdown_content = generate_plugins_markdown(
            plugin_config,
            show_ignored=show_ignored,
            ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
            filtered_plugins=menu_plugins,
        )
        markdown_content = await fill_plugin_status(markdown_content, bot_id, group_id, show_ignored)
        await send_markdown_as_image(markdown_content, style_name, available_styles, matcher, group_id)
        return

    plugin_identifier = args[0]
    plugin_name, error_message = await find_plugin_by_identifier(
        plugin_identifier,
        None if show_ignored else (plugin_config.ignored_plugins if plugin_config else []),
    )

    if error_message:
        await matcher.finish(error_message)
        return

    if not plugin_name:
        await matcher.finish(f"博士，你说的'{plugin_identifier}'是什么呀？")
        return

    if len(args) == 1:
        is_disabled = await is_plugin_disabled(plugin_name, group_id, bot_id, bot=bot, event=event)
        markdown_content, issue = generate_plugin_functions_markdown(plugin_name, plugin_enabled=not is_disabled)
        if issue is HelpMarkdownIssue.PLUGIN_NOT_FOUND:
            await matcher.finish(f"博士，你说的'{resolved_plugin_display(plugin_name)}'是什么呀？")
            return
        await send_markdown_as_image(markdown_content, style_name, available_styles, matcher, group_id)
        return

    if len(args) == 2:
        function_identifier = args[1]
        markdown_content, issue = generate_function_detail_markdown(plugin_name, function_identifier)

        if issue is HelpMarkdownIssue.PLUGIN_NOT_FOUND:
            await matcher.finish(f"博士，你说的'{resolved_plugin_display(plugin_name)}'是什么呀？")
            return
        if issue is HelpMarkdownIssue.FUNCTION_NOT_FOUND:
            await matcher.finish(f"博士，我在'{resolved_plugin_display(plugin_name)}'中没有找到这个功能哦")
            return
        if issue is HelpMarkdownIssue.METADATA_MISSING:
            await matcher.finish(f"博士，'{resolved_plugin_display(plugin_name)}'只有这么多信息了")
            return

        await send_markdown_as_image(markdown_content, style_name, available_styles, matcher, group_id)
        return

    await matcher.finish("博士，你说的太多了，我跟不上了...")


async def handle_plugin_operation(
    bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State, action: str, matcher
):
    """处理插件操作命令，支持群聊和私聊"""
    args: list[str] = list(state.get("toggle_args") or [])
    bot_id, group_id = get_context_info(bot, event)

    is_superuser = await SUPERUSER(bot, event)
    is_private = isinstance(event, PrivateMessageEvent)
    show_ignored = is_superuser and is_private

    plugin_identifier = args[0] if args else ""

    if not plugin_identifier:
        await matcher.finish(f"博士，即使身为大祭司，你不说想要{action}什么，我也帮不了你呀")
        return

    from .styles import load_config

    plugin_config = load_config()
    plugin_name, error_message = await find_plugin_by_identifier(
        plugin_identifier,
        None if show_ignored else (plugin_config.ignored_plugins if plugin_config else []),
    )
    if error_message or plugin_name is None:
        await matcher.finish(error_message or f"博士，你说的'{plugin_identifier}'是什么呀？")
        return

    if is_superuser and len(args) > 1:
        if args[1].lower() == "global":
            group_id = None
        elif args[1].isdigit():
            group_id = int(args[1])

    success, message = await toggle_plugin(plugin_name, group_id, bot_id, action, is_superuser=is_superuser)
    await matcher.finish(message)
