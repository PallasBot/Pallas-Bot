"""多 Bot 同群：拦截其它牛牛消息与 sleep 模式群事件。"""

from __future__ import annotations

from nonebot import on_message, on_notice
from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent, GroupMessageEvent, PokeNotifyEvent, permission
from nonebot.rule import Rule

from pallas.core.foundation.config import BotConfig
from pallas.core.platform.multi_bot.connected_roster import connected_bot_ids, register_connected_roster_hooks
from pallas.core.platform.multi_bot.fleet import fleet_bot_ids_contains
from pallas.core.platform.shard import context as shard_ctx

_matchers_registered = False
_runtime_registered = False


def is_fleet_bot_qq(qq: int) -> bool:
    from pallas.core.platform.federate.peer_bots import federate_peer_bot_ids_contains

    if shard_ctx.sharding_active():
        return fleet_bot_ids_contains(qq) or federate_peer_bot_ids_contains(qq)
    return qq in connected_bot_ids() or federate_peer_bot_ids_contains(qq)


async def is_other_bot(event: GroupMessageEvent) -> bool:
    if not is_fleet_bot_qq(int(event.user_id)):
        return False
    if await BotConfig(event.self_id, event.group_id).is_dreaming():
        return False
    from pallas.core.plugin_coord.duel import is_duel_paired_bot_traffic

    if await is_duel_paired_bot_traffic(event.group_id, int(event.user_id), int(event.self_id)):
        return False
    return True


async def is_sleep(event: GroupMessageEvent | GroupIncreaseNoticeEvent | PokeNotifyEvent) -> bool:
    if not event.group_id:
        return False
    return await BotConfig(event.self_id, event.group_id).is_sleep()


def register_bot_filter_matchers() -> None:
    global _matchers_registered
    if _matchers_registered:
        return

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
    async def _drop_other_bot() -> None:
        return

    @any_msg.handle()
    async def _drop_sleep_msg() -> None:
        return

    @any_notice.handle()
    async def _drop_sleep_notice() -> None:
        return

    _matchers_registered = True


def register_bot_filter_runtime() -> None:
    global _runtime_registered
    from pallas.core.platform.bot_runtime.roles import is_hub_role

    if _runtime_registered or is_hub_role():
        return
    register_connected_roster_hooks()
    register_bot_filter_matchers()
    _runtime_registered = True
