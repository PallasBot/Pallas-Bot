from functools import lru_cache

from nonebot import get_driver, logger
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.internal.matcher import Matcher
from nonebot.message import event_preprocessor, run_preprocessor

from pallas.core.perm.acl import AclSubject, evaluate_acl
from pallas.core.perm.plugin_acl import plugin_acl_key
from pallas.core.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext
from pallas.core.platform.ingress.policy_registry import text_matches_plugin_fanout
from pallas.core.platform.multi_bot.dedup import try_claim_cross_bot_message
from pallas.core.platform.shard import context as shard_ctx

from .plugin_legacy_names import is_plugin_name_in_set
from .plugin_manager import collect_disabled_plugin_names, superuser_bypasses_plugin_disable

_blocked_events: dict[str, frozenset[str]] = {}
_COMMAND_INGRESS_PLUGIN = "command_ingress"


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
    if not text or not (is_plugin_command_plaintext(text) or text_matches_plugin_fanout(text, "help")):
        return True
    from pallas.core.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim

    if ingress_fanout_bypasses_claim(text):
        return True
    if not shard_ctx.sharding_active():
        from pallas.core.platform.ingress.unified_pass import unified_ingress_once_won_for_text

        if unified_ingress_once_won_for_text(group_id, user_id, text, message_time):
            return True
    return await try_claim_cross_bot_message(
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

    try:
        uid = int(event.user_id)
    except Exception:
        uid = None
    if uid is not None:
        plugin_key = plugin_acl_key(plugin_name)
        acl_decision = await evaluate_acl(
            action=plugin_key,
            target=plugin_key,
            subject=AclSubject(user_id=uid, group_id=group_id, bot_id=bot_id),
        )
        if acl_decision.source == "admin_bypass":
            return
        if acl_decision.source == "rule" and not acl_decision.allow:
            logger.debug("bot [{}] plugin [{}] blocked for uid={} by acl", bot_id, plugin_name, uid)
            raise IgnoredException(f"Plugin {plugin_name} blocked for user")

    disabled_names = _blocked_events.get(event_id)
    if disabled_names is None:
        disabled_names = await collect_disabled_plugin_names(bot_id, group_id)
        _blocked_events[event_id] = disabled_names

    if is_plugin_name_in_set(plugin_name, disabled_names):
        if await superuser_bypasses_plugin_disable(bot, event):
            return
        logger.debug(f"bot [{bot_id}] help plugin [{plugin_name}] blocked at matcher")
        raise IgnoredException(f"Plugin {plugin_name} is disabled")


driver = get_driver()


@driver.on_startup
async def register_plugin_manager():
    logger.debug("[帮助] 插件禁用预处理已注册")
