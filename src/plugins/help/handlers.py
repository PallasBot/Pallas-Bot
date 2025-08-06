from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State

from .markdown_generator import (
    generate_function_detail_markdown,
    generate_plugin_functions_markdown,
    generate_plugins_markdown,
)
from .plugin_manager import (
    fill_plugin_status,
    find_plugin_by_identifier,
    is_plugin_disabled,
    toggle_plugin,
)
from .renderer import send_markdown_as_image


def get_context_info(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    bot_id = int(bot.self_id)

    group_id = None
    if isinstance(event, GroupMessageEvent):
        group_id = event.group_id

    return bot_id, group_id


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

    args = event.get_plaintext().strip().split()[1:] if event.get_plaintext() else []
    bot_id, group_id = get_context_info(bot, event)
    style_name = default_style_name

    if len(args) == 0:
        # 一级菜单：显示所有插件列表（包含状态）
        markdown_content = generate_plugins_markdown(plugin_config)
        markdown_content = await fill_plugin_status(markdown_content, bot_id, group_id)
        await send_markdown_as_image(markdown_content, style_name, available_styles, matcher, group_id)
        return

    # 处理插件标识符（适用于二级和三级菜单）
    plugin_identifier = args[0]
    plugin_name, error_message = await find_plugin_by_identifier(
        plugin_identifier, plugin_config.ignored_plugins if plugin_config else []
    )

    if error_message:
        await matcher.finish(error_message)
        return

    # 验证插件是否存在
    markdown_content = generate_plugin_functions_markdown(plugin_config, plugin_name)
    if "未找到插件" in markdown_content:
        await matcher.finish(f"博士，你说的'{plugin_name}'是什么呀？")
        return

    if len(args) == 1:
        # 二级菜单：显示插件功能列表
        is_disabled = await is_plugin_disabled(plugin_name, group_id, bot_id)
        plugin_status = "⛔ 禁用" if is_disabled else "✅ 启用"
        markdown_content = generate_plugin_functions_markdown(plugin_config, plugin_name, plugin_status)
        await send_markdown_as_image(markdown_content, style_name, available_styles, matcher, group_id)
        return

    if len(args) == 2:
        # 三级菜单：显示功能详情
        function_identifier = args[1]
        markdown_content = generate_function_detail_markdown(plugin_config, plugin_name, function_identifier)

        # 处理可能的错误
        if "未找到功能" in markdown_content:
            await matcher.finish(f"博士，你说的'{plugin_name}'是什么呀？")
        elif "错误" in markdown_content:
            await matcher.finish(f"博士，'{plugin_name}'只有这么多信息了")

        await send_markdown_as_image(markdown_content, style_name, available_styles, matcher, group_id)
        return

    # 参数过多
    await matcher.finish("博士，你说的太多了，我跟不上了...")


async def handle_plugin_operation(
    bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State, action: str, matcher
):
    """处理插件操作命令，支持群聊和私聊"""
    # 获取命令参数和上下文信息
    args = event.get_plaintext().strip().split()[1:] if event.get_plaintext() else []
    bot_id, group_id = get_context_info(bot, event)

    plugin_identifier = state.get("plugin_name", "") or (args[0] if args else "")

    if not plugin_identifier:
        await matcher.finish(f"博士，即使身为大祭司，你不说想要{action}什么，我也帮不了你呀")
        return

    plugin_name, error_message = await find_plugin_by_identifier(plugin_identifier)
    if error_message or plugin_name is None:
        await matcher.finish(error_message or f"博士，你说的'{plugin_name}'是什么呀？")
        return

    # 超级用户可以指定全局操作或特定群
    is_superuser = await SUPERUSER(bot, event)
    if is_superuser and len(args) > 1:
        if args[1].lower() == "global":
            group_id = None  # 全局操作
        elif args[1].isdigit():
            group_id = int(args[1])  # 指定群

    success, message = await toggle_plugin(plugin_name, group_id, bot_id, action)
    await matcher.finish(message)
