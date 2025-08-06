from nonebot import get_driver, get_loaded_plugins, logger
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.internal.matcher import Matcher
from nonebot.message import event_preprocessor, run_preprocessor

from .plugin_manager import is_plugin_disabled

_blocked_events: dict[str, set[str]] = {}


IGNORED_PLUGINS = ["help"]


def get_plugin_name_from_matcher(matcher: Matcher) -> str:
    """从Matcher对象获取插件名称"""

    module_name = matcher.plugin_name
    if module_name:
        parts = module_name.split(".")
        for part in reversed(parts):
            if part != "__init__":
                return part

    return module_name or "unknown"


@event_preprocessor
async def block_disabled_plugins(bot: Bot, event: GroupMessageEvent):
    """
    在事件预处理阶段检查插件是否被禁用
    """

    if not isinstance(event, GroupMessageEvent):
        return

    event_id = f"{bot.self_id}_{event.message_id}_{event.group_id}"

    # 为每个新事件创建一个空集合
    _blocked_events[event_id] = set()

    bot_id = int(bot.self_id)
    group_id = event.group_id

    plugins = get_loaded_plugins()

    for plugin in plugins:
        if not plugin.name:
            continue

        plugin_name = plugin.name

        if plugin_name.lower() in IGNORED_PLUGINS:
            continue

        is_disabled = await is_plugin_disabled(plugin_name, group_id, bot_id)

        if is_disabled:
            _blocked_events[event_id].add(plugin_name)
            logger.debug(f"插件 {plugin_name} 在群 {group_id} 对Bot {bot_id} 处于禁用状态")

    if len(_blocked_events) > 10000:
        keys = list(_blocked_events.keys())
        for key in keys[:-1000]:
            _blocked_events.pop(key, None)


@run_preprocessor
async def check_plugin_enabled(matcher: Matcher, bot: Bot, event: GroupMessageEvent):
    """
    在matcher执行前检查插件是否被禁用
    """
    if not isinstance(event, GroupMessageEvent):
        return
    plugin_name = get_plugin_name_from_matcher(matcher)
    if not plugin_name:
        return

    if plugin_name.lower() in IGNORED_PLUGINS:
        return

    event_id = f"{bot.self_id}_{event.message_id}_{event.group_id}"
    bot_id = int(bot.self_id)
    group_id = event.group_id

    if event_id in _blocked_events and plugin_name in _blocked_events[event_id]:
        logger.debug(f"{plugin_name} 已禁用")
        raise IgnoredException(f"Plugin {plugin_name} is disabled")

    # 如果事件ID不在缓存中，直接检查数据库（可能是预处理器没有运行）
    if event_id not in _blocked_events:
        is_disabled = await is_plugin_disabled(plugin_name, group_id, bot_id)
        if is_disabled:
            logger.debug(f"{plugin_name} 已禁用")
            raise IgnoredException(f"Plugin {plugin_name} is disabled")


driver = get_driver()


@driver.on_startup
async def register_plugin_manager():
    logger.info("Plugin manager registered")
