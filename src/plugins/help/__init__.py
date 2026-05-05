from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent, permission
from nonebot.permission import SUPERUSER, Permission
from nonebot.plugin import PluginMetadata
from nonebot.typing import T_State

from src.common.config import BotConfig, GroupConfig

from .config import Config
from .event_preprocessor import IGNORED_PLUGINS

# 导入处理函数
from .handlers import (
    handle_help_command,
    handle_plugin_operation,
)
from .styles import get_default_style, load_config, load_custom_styles

__plugin_meta__ = PluginMetadata(
    name="帮助系统",
    description="显示所有功能的帮助信息，管理功能启用/禁用",
    usage="""
牛牛帮助 — 显示所有插件的简要说明及启用状态
牛牛帮助 <插件名或序号> — 显示指定插件的功能列表与状态
牛牛帮助 <插件名或序号> <功能序号或名称> — 显示指定功能的详细说明

插件开关（插件名支持中文展示名或与包名一致的英文标识）：
牛牛开启 <插件名或序号> — 启用指定插件
牛牛关闭 <插件名或序号> — 禁用指定插件
牛牛开启全部功能 — 启用全部插件（仅群管理员或超级用户）
牛牛关闭全部功能 — 禁用全部插件（仅群管理员或超级用户）
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "显示帮助信息",
                "trigger_method": "on_cmd",
                "trigger_condition": "牛牛帮助",
                "brief_des": "显示所有功能的帮助信息",
                "detail_des": "显示所有已加载功能的元数据信息，包括功能名称、描述、使用方法等，将以图片形式展示",
            },
            {
                "func": "详细帮助信息",
                "trigger_method": "on_cmd",
                "trigger_condition": "牛牛帮助 <插件名或序号>",
                "brief_des": "显示指定插件的详细帮助信息",
                "detail_des": "展示该插件描述、用法及功能列表；插件名可用中文展示名、序号或与包名一致的英文标识",
            },
            {
                "func": "插件开关",
                "trigger_method": "on_cmd",
                "trigger_condition": "牛牛开启/关闭 <插件名或序号>",
                "brief_des": "启用或禁用指定插件",
                "detail_des": "例如「牛牛开启 牛牛复读」「牛牛关闭 1」；插件名规则与「牛牛帮助」一致",
            },
        ],
        "menu_template": "default",
    },
)

plugin_config = get_plugin_config(Config)

# 初始化配置和样式
AVAILABLE_STYLES = load_custom_styles(plugin_config)
DEFAULT_STYLE_NAME = get_default_style(plugin_config)


help_cmd = on_command("牛牛帮助", priority=5, block=True)

HELP_COOLDOWN_KEY = "help"


async def is_config_admin(event: GroupMessageEvent) -> bool:
    return await BotConfig(event.self_id).is_admin_of_bot(event.user_id)


IsAdmin = permission.GROUP_OWNER | permission.GROUP_ADMIN | Permission(is_config_admin)

plugin_enable_cmd = on_command("牛牛开启", priority=5, block=True, permission=IsAdmin | SUPERUSER)

plugin_disable_cmd = on_command("牛牛关闭", priority=5, block=True, permission=IsAdmin | SUPERUSER)

plugin_enable_all_cmd = on_command("牛牛开启全部功能", priority=5, block=True, permission=IsAdmin | SUPERUSER)

plugin_disable_all_cmd = on_command("牛牛关闭全部功能", priority=5, block=True, permission=IsAdmin | SUPERUSER)


@help_cmd.handle()
async def handle_help_cmd(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理帮助命令（群聊和私聊）"""
    if isinstance(event, GroupMessageEvent):
        config = GroupConfig(event.group_id, cooldown=3)
        if not await config.is_cooldown(HELP_COOLDOWN_KEY):
            await help_cmd.finish()
            return
        await config.refresh_cooldown(HELP_COOLDOWN_KEY)

    await handle_help_command(bot, event, state, plugin_config, AVAILABLE_STYLES, DEFAULT_STYLE_NAME, help_cmd)


def extract_plugin_name_from_command(event: GroupMessageEvent | PrivateMessageEvent, prefix: str) -> str:
    """从命令文本中提取插件名称"""
    message_text = event.get_plaintext().strip()
    if message_text.startswith(prefix):
        args = message_text[len(prefix) :].strip().split()
        return args[0] if args else ""
    return ""


@plugin_enable_cmd.handle()
async def handle_enable_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理功能启用命令"""
    plugin_name = extract_plugin_name_from_command(event, "牛牛开启")
    if not plugin_name:
        await plugin_enable_cmd.finish("博士，即使身为大祭司，你不说想要开启什么，我也帮不了你呀")
        return

    state["plugin_name"] = plugin_name
    await handle_plugin_operation(bot, event, state, "enable", plugin_enable_cmd)


@plugin_disable_cmd.handle()
async def handle_disable_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理功能禁用命令"""
    plugin_name = extract_plugin_name_from_command(event, "牛牛关闭")
    if not plugin_name:
        await plugin_disable_cmd.finish("博士，即使身为大祭司，你不说想要关闭什么，我也帮不了你呀")
        return

    state["plugin_name"] = plugin_name
    await handle_plugin_operation(bot, event, state, "disable", plugin_disable_cmd)


async def toggle_all_plugins(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, action: str, matcher):
    """处理启用/禁用所有功能的命令"""
    from nonebot import get_loaded_plugins

    from .handlers import get_context_info
    from .plugin_manager import toggle_plugin

    bot_id, group_id = get_context_info(bot, event)

    # 获取所有已加载的功能并过滤
    plugins = [p for p in get_loaded_plugins() if p.name and p.name.lower() not in IGNORED_PLUGINS]

    count = 0
    for plugin in plugins:
        success, _ = await toggle_plugin(plugin.name, group_id, bot_id, action=action)
        if success:
            count += 1

    action_name = "启用" if action == "enable" else "停止"
    await matcher.finish(f"在米诺斯女神的允许下，我将{action_name} {count} 个能力")


@plugin_enable_all_cmd.handle()
async def handle_enable_all_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理启用所有功能的命令"""
    await toggle_all_plugins(bot, event, "enable", plugin_enable_all_cmd)


@plugin_disable_all_cmd.handle()
async def handle_disable_all_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理禁用所有功能的命令"""
    await toggle_all_plugins(bot, event, "disable", plugin_disable_all_cmd)
