from nonebot import on_command, on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from src.features.cmd_perm import permission_for_command
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_BOTH, SCENE_GROUP, join_usage, usage_line
from src.foundation.command_prefix import matches_command_prefix
from src.foundation.config import BotConfig, GroupConfig

from .config import Config, get_help_config, plugin_config
from .event_preprocessor import IGNORED_PLUGINS  # noqa: F401

# 导入处理函数
from .handlers import (
    handle_help_command,
    handle_plugin_operation,
)
from .help_args import (
    HELP_COMMAND,
    PLUGIN_DISABLE_COMMAND,
    PLUGIN_ENABLE_COMMAND,
    parse_plugin_toggle_args,
)
from .plugin_manager import get_help_menu_plugins
from .styles import get_default_style, load_config, load_custom_styles

__plugin_meta__ = PluginMetadata(
    name="牛牛帮助",
    description="三级帮助图与群内插件开关。",
    usage=join_usage(
        usage_line("牛牛帮助", "插件总览与开关状态"),
        usage_line("牛牛帮助 〈插件名或序号〉", "单插件功能表"),
        usage_line("牛牛帮助 〈插件〉 〈功能序号或名称〉", "单条功能详情"),
        usage_line("牛牛开启 / 牛牛关闭 〈插件名或序号〉", "本群开关某插件"),
        usage_line("牛牛开启全部功能 / 牛牛关闭全部功能", "本群批量开关"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_fanout": {
            "scope": "unified_only",
            "prefixes": [
                "牛牛帮助",
                "牛牛开启",
                "牛牛关闭",
                "牛牛开启全部功能",
                "牛牛关闭全部功能",
            ],
        },
        "command_permissions": [
            {"id": "help.help", "label": "牛牛帮助", "default": "everyone"},
            {"id": "help.plugin_enable", "label": "牛牛开启（单插件）", "default": "staff"},
            {"id": "help.plugin_disable", "label": "牛牛关闭（单插件）", "default": "staff"},
            {"id": "help.plugin_enable_all", "label": "牛牛开启全部功能", "default": "staff"},
            {"id": "help.plugin_disable_all", "label": "牛牛关闭全部功能", "default": "staff"},
        ],
        "menu_data": [
            {
                "func": "总列表",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛帮助",
                "command_permission": "help.help",
                "brief_des": "全部插件、状态与简介",
                "detail_des": "看图可知本群各插件是否启用；用序号或中文名继续打开下级。",
            },
            {
                "func": "插件详情",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛帮助 〈插件名或序号〉",
                "command_permission": "help.help",
                "brief_des": "单插件说明与功能表",
                "detail_des": "含用法与「怎么说 / 场景 / 何人可用」；可再跟功能序号或名称看详情。",
            },
            {
                "func": "功能详情",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛帮助 〈插件〉 〈功能序号或名称〉",
                "command_permission": "help.help",
                "brief_des": "单条功能的口令与说明",
                "detail_des": "展示完整口令、场景与「何人可用」。",
            },
            {
                "func": "插件开关",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛开启 / 牛牛关闭 〈插件名或序号〉",
                "command_permissions": ["help.plugin_enable", "help.plugin_disable"],
                "brief_des": "本群启用或停用某插件",
                "detail_des": "例：牛牛开启 牛牛复读、牛牛关闭 1；命名规则同打开插件详情。",
            },
            {
                "func": "批量开关",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛开启全部功能 / 牛牛关闭全部功能",
                "command_permissions": ["help.plugin_enable_all", "help.plugin_disable_all"],
                "brief_des": "本群一键全开或全关",
                "detail_des": "仅切换帮助总览中列出的插件，与总览数量一致。",
            },
        ],
    },
)


def refresh_style_cache(cfg: Config | None = None) -> None:
    global AVAILABLE_STYLES, DEFAULT_STYLE_NAME
    c = cfg or get_help_config()
    AVAILABLE_STYLES = load_custom_styles(c)
    DEFAULT_STYLE_NAME = get_default_style(c)


refresh_style_cache()


def help_command_rule() -> Rule:
    async def _match_help_command(event: Event, state: T_State) -> bool:
        del state
        try:
            plain = event.get_plaintext()
        except Exception:
            return False
        return matches_command_prefix(plain, HELP_COMMAND)

    return Rule(_match_help_command)


help_cmd = on_message(
    help_command_rule(),
    priority=5,
    block=True,
    permission=permission_for_command("help.help"),
)

HELP_COOLDOWN_KEY = "help"

plugin_enable_cmd = on_command(
    "牛牛开启", priority=5, block=True, permission=permission_for_command("help.plugin_enable")
)

plugin_disable_cmd = on_command(
    "牛牛关闭", priority=5, block=True, permission=permission_for_command("help.plugin_disable")
)

plugin_enable_all_cmd = on_command(
    "牛牛开启全部功能", priority=5, block=True, permission=permission_for_command("help.plugin_enable_all")
)

plugin_disable_all_cmd = on_command(
    "牛牛关闭全部功能", priority=5, block=True, permission=permission_for_command("help.plugin_disable_all")
)


@help_cmd.handle()
async def handle_help_cmd(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理帮助命令"""
    if isinstance(event, GroupMessageEvent):
        config = GroupConfig(event.group_id, cooldown=3)
        if not await config.is_cooldown(HELP_COOLDOWN_KEY):
            await help_cmd.finish()
            return
        await config.refresh_cooldown(HELP_COOLDOWN_KEY)

    await handle_help_command(bot, event, state, plugin_config, AVAILABLE_STYLES, DEFAULT_STYLE_NAME, help_cmd)


def _toggle_command_plugin_count() -> int:
    return len(
        get_help_menu_plugins(
            show_ignored=False,
            ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
        )
    )


@plugin_enable_cmd.handle()
async def handle_enable_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理功能启用命令"""
    args = parse_plugin_toggle_args(
        event.get_plaintext() or "",
        PLUGIN_ENABLE_COMMAND,
        plugin_count=_toggle_command_plugin_count(),
    )
    if not args:
        await plugin_enable_cmd.finish("博士，即使身为大祭司，你不说想要开启什么，我也帮不了你呀")
        return

    state["toggle_args"] = args
    await handle_plugin_operation(bot, event, state, "enable", plugin_enable_cmd)


@plugin_disable_cmd.handle()
async def handle_disable_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理功能禁用命令"""
    args = parse_plugin_toggle_args(
        event.get_plaintext() or "",
        PLUGIN_DISABLE_COMMAND,
        plugin_count=_toggle_command_plugin_count(),
    )
    if not args:
        await plugin_disable_cmd.finish("博士，即使身为大祭司，你不说想要关闭什么，我也帮不了你呀")
        return

    state["toggle_args"] = args
    await handle_plugin_operation(bot, event, state, "disable", plugin_disable_cmd)


async def toggle_all_plugins(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, action: str, matcher):
    """处理启用/禁用所有功能的命令"""
    from nonebot.permission import SUPERUSER

    from .handlers import get_context_info
    from .plugin_manager import get_help_menu_plugins, toggle_plugin

    bot_id, group_id = get_context_info(bot, event)
    is_superuser = await SUPERUSER(bot, event)
    plugin_config = load_config()
    plugins = get_help_menu_plugins(
        show_ignored=False,
        ignored_plugins=plugin_config.ignored_plugins if plugin_config else [],
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
    """处理启用所有功能的命令"""
    await toggle_all_plugins(bot, event, "enable", plugin_enable_all_cmd)


@plugin_disable_all_cmd.handle()
async def handle_disable_all_command(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    """处理禁用所有功能的命令"""
    await toggle_all_plugins(bot, event, "disable", plugin_disable_all_cmd)
