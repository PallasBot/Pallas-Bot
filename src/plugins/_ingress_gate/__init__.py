"""分片 worker 专用预处理器：fleet 识别、@ 定向、全局 claim、fanout。"""

from __future__ import annotations

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

from src.common.bot_runtime.roles import is_hub_role
from src.common.ingress.cage_plaintext import is_cage_plaintext
from src.common.multi_bot.dedup import try_claim_cross_bot_message
from src.common.multi_bot.fleet import fleet_bot_ids_contains, get_fleet_bot_ids
from src.common.shard.coord.bot_count import should_skip_ingress_claim_for_shard_bot_count
from src.common.shard.ingress_fanout import is_ingress_fanout_plaintext
from src.common.shard.registry.config import is_sharding_active

INGRESS_CLAIM_PLUGIN = "ingress_gate"
driver = get_driver()


def ingress_gate_active() -> bool:
    if is_hub_role():
        return False
    return True


def group_at_qq_ids(event: GroupMessageEvent) -> frozenset[int]:
    out: set[int] = set()
    for seg in event.message:
        if seg.type != "at":
            continue
        qq = seg.data.get("qq")
        if qq is None or str(qq) in ("all", "0"):
            continue
        try:
            out.add(int(qq))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


@event_preprocessor
async def ingress_group_message_gate(bot, event) -> None:
    if not ingress_gate_active():
        return
    if not isinstance(event, GroupMessageEvent):
        return

    self_id = int(bot.self_id)
    user_id = int(event.user_id)

    if fleet_bot_ids_contains(user_id) and user_id != self_id:
        raise IgnoredException("fleet bot message")

    ats = group_at_qq_ids(event)
    if ats:
        fleet = get_fleet_bot_ids()
        pallas_ats = ats & fleet
        if pallas_ats and self_id not in pallas_ats:
            raise IgnoredException("not at-target bot")

    plain = (event.get_plaintext() or "").strip()
    if is_sharding_active() and (
        is_ingress_fanout_plaintext(plain)
        or should_skip_ingress_claim_for_shard_bot_count(plain)
        or is_cage_plaintext(plain)
    ):
        return

    body = plain or event.raw_message
    if not await try_claim_cross_bot_message(
        INGRESS_CLAIM_PLUGIN,
        event.group_id,
        user_id,
        body,
        event.time,
        self_id,
        use_plaintext=True,
    ):
        raise IgnoredException("ingress claim lost")


@driver.on_startup
async def _log_ingress_gate() -> None:
    if not ingress_gate_active():
        return
    n = len(get_fleet_bot_ids())
    mode = "shard" if is_sharding_active() else "unified"
    logger.info("ingress_gate: active mode={} fleet_bots={}", mode, n)
