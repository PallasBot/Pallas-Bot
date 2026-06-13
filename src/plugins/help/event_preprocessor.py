from functools import lru_cache

from nonebot import get_driver, logger
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.internal.matcher import Matcher
from nonebot.message import event_preprocessor, run_preprocessor

from src.platform.ingress.help_plaintext import is_help_plaintext
from src.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext
from src.platform.multi_bot.dedup import try_claim_cross_bot_message, try_claim_cross_bot_message_memory
from src.platform.shard.registry.config import is_sharding_active

from .plugin_manager import collect_disabled_plugin_names, superuser_bypasses_plugin_disable

_blocked_events: dict[str, frozenset[str]] = {}
_COMMAND_INGRESS_PLUGIN = "command_ingress"
_SHARDED_COMMAND_INGRESS_PLUGIN = "ingress_gate"


IGNORED_PLUGINS = ["help"]


@lru_cache(maxsize=512)
def _plugin_name_from_module_name(module_name: str | None) -> str:
    if not module_name:
        return "unknown"
    parts = module_name.split(".")
    for part in reversed(parts):
        if part != "__init__":
            return part
    return module_name or "unknown"


def get_plugin_name_from_matcher(matcher: Matcher) -> str:
    """从Matcher对象获取插件名称"""
    return _plugin_name_from_module_name(matcher.plugin_name)


async def command_cross_bot_claim_won(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    plain_text: str,
    message_time: int,
) -> bool:
    text = (plain_text or "").strip()
    if not text or not (is_plugin_command_plaintext(text) or is_help_plaintext(text)):
        return True
    from src.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim

    if ingress_fanout_bypasses_claim(text):
        return True
    if is_sharding_active():
        return await try_claim_cross_bot_message(
            _SHARDED_COMMAND_INGRESS_PLUGIN,
            group_id,
            user_id,
            text,
            message_time,
            bot_id,
            use_plaintext=True,
            include_message_time=True,
        )
    return await try_claim_cross_bot_message_memory(
        _COMMAND_INGRESS_PLUGIN,
        group_id,
        user_id,
        text,
        message_time,
        bot_id,
        use_plaintext=True,
        include_message_time=True,
    )


@event_preprocessor
async def block_disabled_plugins(bot: Bot, event: GroupMessageEvent):
    """仅维护 event_id 缓存表；禁用列表在 run_preprocessor 首次命中时加载。"""

    if not isinstance(event, GroupMessageEvent):
        return

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

    bot_id = int(bot.self_id)
    if not await command_cross_bot_claim_won(
        bot_id=bot_id,
        group_id=event.group_id,
        user_id=event.user_id,
        plain_text=event.get_plaintext(),
        message_time=event.time,
    ):
        logger.debug("bot [{}] command matcher [{}] skipped by cross-bot claim", bot_id, plugin_name)
        raise IgnoredException(f"Command matcher skipped for bot {bot_id}")

    event_id = f"{bot.self_id}_{event.message_id}_{event.group_id}"
    group_id = event.group_id

    disabled_names = _blocked_events.get(event_id)
    if disabled_names is None:
        disabled_names = await collect_disabled_plugin_names(bot_id, group_id)
        _blocked_events[event_id] = disabled_names

    if plugin_name in disabled_names:
        if await superuser_bypasses_plugin_disable(bot, event):
            return
        logger.debug(f"bot [{bot_id}] help plugin [{plugin_name}] blocked at matcher")
        raise IgnoredException(f"Plugin {plugin_name} is disabled")


driver = get_driver()


@driver.on_startup
async def register_plugin_manager():
    logger.info("help plugin_manager event_preprocessors registered")
