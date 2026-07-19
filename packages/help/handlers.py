from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State

from .help_args import parse_help_args, parse_help_page_token
from .markdown_generator import HelpMarkdownIssue
from .menu_rows import build_help_menu_rows, paginate_menu_rows
from .plugin_detail_data import (
    build_function_detail_data,
    build_plugin_detail_data,
    find_command_help_targets,
)
from .plugin_manager import (
    find_plugin,
    find_plugin_by_identifier,
    get_help_menu_plugins,
    is_plugin_disabled_for_help_display,
    plugin_display_name,
    toggle_plugin,
)
from .renderer import send_function_detail_image, send_plugin_detail_image, send_plugin_menu_image


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

    is_superuser = await SUPERUSER(bot, event)
    is_private = isinstance(event, PrivateMessageEvent)
    show_ignored = is_superuser and is_private

    menu_plugins = get_help_menu_plugins(
        show_ignored=show_ignored,
        ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
    )
    args = parse_help_args(event.get_plaintext() or "", plugin_count=len(menu_plugins))

    if len(args) == 0:
        all_rows = await build_help_menu_rows(
            bot_id=bot_id,
            group_id=group_id,
            show_ignored=show_ignored,
        )
        page_rows, page, total_pages = paginate_menu_rows(all_rows, page=1)
        enabled_count = sum(1 for row in all_rows if row.enabled)
        await send_plugin_menu_image(
            page_rows,
            show_ignored=show_ignored,
            matcher=matcher,
            group_id=group_id,
            page=page,
            total_pages=total_pages,
            total_plugin_count=len(all_rows),
            total_enabled_count=enabled_count,
        )
        return

    if len(args) == 1:
        page_token = parse_help_page_token(args[0])
        if page_token is not None:
            all_rows = await build_help_menu_rows(
                bot_id=bot_id,
                group_id=group_id,
                show_ignored=show_ignored,
            )
            page_rows, page, total_pages = paginate_menu_rows(all_rows, page=page_token)
            if page_token > total_pages:
                await matcher.finish(f"博士，帮助总览只有 {total_pages} 页哦")
                return
            enabled_count = sum(1 for row in all_rows if row.enabled)
            await send_plugin_menu_image(
                page_rows,
                show_ignored=show_ignored,
                matcher=matcher,
                group_id=group_id,
                page=page,
                total_pages=total_pages,
                total_plugin_count=len(all_rows),
                total_enabled_count=enabled_count,
            )
            return

    plugin_identifier = args[0]
    ignored_plugins = None if show_ignored else (plugin_config.ignored_plugins if plugin_config else [])
    plugin_name, error_message = await find_plugin_by_identifier(plugin_identifier, ignored_plugins)

    if len(args) == 1:
        # 优先按插件名/序号展示插件详情；命中唯一插件时与旧行为一致
        if plugin_name and not error_message:
            is_disabled = await is_plugin_disabled_for_help_display(
                plugin_name,
                group_id,
                bot_id,
                bot=bot,
                event=event,
            )
            detail_data, issue = build_plugin_detail_data(plugin_name, plugin_enabled=not is_disabled)
            if issue is HelpMarkdownIssue.PLUGIN_NOT_FOUND:
                await matcher.finish(f"博士，你说的'{resolved_plugin_display(plugin_name)}'是什么呀？")
                return
            assert detail_data is not None
            await send_plugin_detail_image(detail_data, matcher=matcher, group_id=group_id)
            return

        # 非插件名时，尝试把单条参数当作口令/功能名，跨插件直达功能详情页
        targets = find_command_help_targets(
            plugin_identifier,
            show_ignored=show_ignored,
            ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
        )
        if len(targets) == 1:
            target = targets[0]
            detail_data, issue = build_function_detail_data(target.plugin_name, target.func_name)
            if issue is HelpMarkdownIssue.OK and detail_data is not None:
                await send_function_detail_image(detail_data, matcher=matcher, group_id=group_id)
                return
        elif len(targets) > 1:
            preview = "、".join(f"{t.plugin_display}·{t.func_name}" for t in targets[:6])
            suffix = " 等" if len(targets) > 6 else ""
            await matcher.finish(
                f"博士，'{plugin_identifier}'可能指这些功能：{preview}{suffix}，"
                f"可以发「牛牛帮助 插件 功能」再看具体说明哦"
            )
            return

        await matcher.finish(error_message or f"博士，你说的'{plugin_identifier}'是什么呀？")
        return

    if error_message:
        await matcher.finish(error_message)
        return

    if not plugin_name:
        await matcher.finish(f"博士，你说的'{plugin_identifier}'是什么呀？")
        return

    if len(args) == 2:
        function_identifier = args[1]
        detail_data, issue = build_function_detail_data(plugin_name, function_identifier)

        if issue is HelpMarkdownIssue.PLUGIN_NOT_FOUND:
            await matcher.finish(f"博士，你说的'{resolved_plugin_display(plugin_name)}'是什么呀？")
            return
        if issue is HelpMarkdownIssue.FUNCTION_NOT_FOUND:
            await matcher.finish(f"博士，我在'{resolved_plugin_display(plugin_name)}'中没有找到这个功能哦")
            return
        if issue is HelpMarkdownIssue.METADATA_MISSING:
            await matcher.finish(f"博士，'{resolved_plugin_display(plugin_name)}'只有这么多信息了")
            return
        assert detail_data is not None
        await send_function_detail_image(detail_data, matcher=matcher, group_id=group_id)
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
