import asyncio

from nonebot import get_driver, logger, on_message, on_notice
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent, GroupMessageEvent, PokeNotifyEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import join_usage, usage_line
from src.foundation.config import BotConfig
from src.platform.multi_bot.fleet import fleet_bot_ids_contains
from src.platform.multi_bot.session_seen import note_bot_session_seen
from src.platform.shard.presence import (
    clear_protocol_bot_offline,
    note_worker_bot_connected,
    note_worker_bot_disconnected,
)
from src.platform.shard.registry.config import is_sharding_active

from .config import Config, plugin_config

__plugin_meta__ = PluginMetadata(
    name="其他牛牛拦截",
    description="拦截其它牛牛账号在本群的群消息与通知。",
    usage=join_usage(
        usage_line("（内部）", "多 Bot 同群时避免互相触发"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "menu_data": [
            {
                "func": "消息拦截",
                "trigger_method": "on_message/on_notice",
                "help_audience": "maintainer",
                "trigger_condition": "内部拦截",
                "brief_des": "拦截群事件",
                "detail_des": "阻断群消息与通知，避免触发后续插件逻辑。",
            },
        ],
    },
)

driver = get_driver()


@driver.on_bot_connect
async def bot_connect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        logger.info(f"Bot {bot.self_id} connected.")
        qq = int(bot.self_id)
        plugin_config.bots.add(qq)
        note_bot_session_seen(qq)
        await clear_protocol_bot_offline(qq)
        if is_sharding_active():
            await note_worker_bot_connected(bot)
        try:
            from src.platform.federate.peer_bots import sync_federate_peer_bot_roster

            asyncio.create_task(sync_federate_peer_bot_roster(), name=f"federate_peer_sync_connect:{qq}")
        except Exception:
            pass


@driver.on_bot_disconnect
async def bot_disconnect(bot: Bot) -> None:
    if bot.self_id.isnumeric() and bot.type == "OneBot V11":
        qq = int(bot.self_id)
        was_present = qq in plugin_config.bots
        plugin_config.bots.discard(qq)
        if was_present:
            logger.info(f"Bot {bot.self_id} disconnected.")
        await clear_protocol_bot_offline(qq)
        if is_sharding_active():
            await note_worker_bot_disconnected(qq)
        try:
            from src.platform.federate.peer_bots import sync_federate_peer_bot_roster

            asyncio.create_task(
                sync_federate_peer_bot_roster(),
                name=f"federate_peer_sync_disconnect:{int(bot.self_id)}",
            )
        except Exception:
            pass


def is_fleet_bot_qq(qq: int) -> bool:
    from src.platform.federate.peer_bots import federate_peer_bot_ids_contains

    if is_sharding_active():
        return fleet_bot_ids_contains(qq) or federate_peer_bot_ids_contains(qq)
    return qq in plugin_config.bots or federate_peer_bot_ids_contains(qq)


async def is_other_bot(event: GroupMessageEvent) -> bool:
    if not is_fleet_bot_qq(int(event.user_id)):
        return False
    if await BotConfig(event.self_id, event.group_id).is_dreaming():
        return False
    from src.plugins.duel.duel_session import is_duel_paired_bot_traffic

    if await is_duel_paired_bot_traffic(event.group_id, int(event.user_id), int(event.self_id)):
        return False
    return True


async def is_sleep(event: GroupMessageEvent | GroupIncreaseNoticeEvent | PokeNotifyEvent) -> bool:
    if not event.group_id:
        return False
    return await BotConfig(event.self_id, event.group_id).is_sleep()


other_bot_msg = on_message(
    priority=1,
    block=True,
    rule=Rule(is_other_bot),
    permission=permission.GROUP,
)

any_msg = on_message(
    priority=4,
    block=True,
    rule=Rule(is_sleep),
    permission=permission.GROUP,
)

any_notice = on_notice(
    priority=4,
    block=True,
    rule=Rule(is_sleep),
)


@other_bot_msg.handle()
async def _():
    return
