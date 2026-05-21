from nonebot import get_driver, logger
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.internal.matcher import Matcher
from nonebot.message import event_preprocessor, run_preprocessor

from .plugin_manager import collect_disabled_plugin_names
from .visibility import PLUGIN_DISABLE_EXEMPT

_blocked_events: dict[str, frozenset[str]] = {}


def get_plugin_name_from_matcher(matcher: Matcher) -> str:
    """从Matcher对象获取插件名称"""

    module_name = matcher.plugin_name
    if module_name:
        parts = module_name.split(".")
        for part in reversed(parts):
            if part != "__init__":
                return part

    return module_name or "unknown"


def group_message_needs_disabled_plugin_lookup(event: GroupMessageEvent) -> bool:
    """仅对可能触发插件的群消息预取禁用列表，避免纯闲聊也打配置库。"""
    plain = event.get_plaintext().strip()
    if plain.startswith("牛牛"):
        return True
    try:
        if event.is_tome():
            return True
    except Exception:
        pass
    return False


@event_preprocessor
async def block_disabled_plugins(bot: Bot, event: GroupMessageEvent):
    """
    在事件预处理阶段检查插件是否被禁用
    """

    if not isinstance(event, GroupMessageEvent):
        return

    if not group_message_needs_disabled_plugin_lookup(event):
        return

    event_id = f"{bot.self_id}_{event.message_id}_{event.group_id}"

    bot_id = int(bot.self_id)
    group_id = event.group_id

    disabled_names = await collect_disabled_plugin_names(bot_id, group_id)
    _blocked_events[event_id] = disabled_names
    if disabled_names:
        logger.debug(f"bot [{bot_id}] help disabled plugins in group [{group_id}]: {', '.join(sorted(disabled_names))}")

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

    if plugin_name.lower() in PLUGIN_DISABLE_EXEMPT:
        return

    event_id = f"{bot.self_id}_{event.message_id}_{event.group_id}"
    bot_id = int(bot.self_id)
    group_id = event.group_id

    disabled_names = _blocked_events.get(event_id)
    if disabled_names is None:
        disabled_names = await collect_disabled_plugin_names(bot_id, group_id)
        _blocked_events[event_id] = disabled_names

    if plugin_name in disabled_names:
        logger.debug(f"bot [{bot_id}] help plugin [{plugin_name}] blocked at matcher")
        raise IgnoredException(f"Plugin {plugin_name} is disabled")


driver = get_driver()


@driver.on_startup
async def register_plugin_manager():
    logger.info("help plugin_manager event_preprocessors registered")
