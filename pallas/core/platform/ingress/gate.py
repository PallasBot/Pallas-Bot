"""群消息入站预处理与跨机去重。"""

from __future__ import annotations

import asyncio

from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, NoticeEvent
from nonebot.exception import IgnoredException

from pallas.core.platform.federate.config import federate_ingress_bypass_unified
from pallas.core.platform.federate.ingress import claim_federate_group_message_ingress
from pallas.core.platform.federate.peer_bots import (
    federate_peer_bot_ids_contains,
    should_process_federate_group_on_current_deployment,
    start_federate_peer_bot_sync_loop,
    sync_federate_peer_bot_roster,
)
from pallas.core.platform.ingress.claim_gate import (
    IngressClaimError,
    ingress_gate_runtime_active,
    run_ingress_message_claim,
)
from pallas.core.platform.ingress.dream_host_gate import dream_session_ingress_passes
from pallas.core.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim
from pallas.core.platform.ingress.fast_path import ingress_once_claim_safe_before_host_gates
from pallas.core.platform.ingress.hosted_activity_gate import hosted_activity_ingress_passes
from pallas.core.platform.ingress.notice_gate import ingress_notice_gate
from pallas.core.platform.multi_bot.at_targets import group_at_qq_ids, message_at_fleet_bot
from pallas.core.platform.multi_bot.fleet import fleet_bot_ids_contains, get_fleet_bot_ids
from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms
from pallas.core.platform.shard import context as shard_ctx
from pallas.core.platform.shard.ingress_metrics import (
    record_ingress_claim,
    record_ingress_early_discard,
    record_ingress_event,
    record_ingress_fanout_bypass,
    should_record_ingress_metrics,
)

_GATE_REGISTERED = False


def ingress_gate_active() -> bool:
    return ingress_gate_runtime_active()


def pallas_at_targets(event: GroupMessageEvent) -> frozenset[int]:
    ats = group_at_qq_ids(event)
    if not ats:
        return frozenset()
    return ats & get_fleet_bot_ids()


def ingress_fanout_early_exit(
    *,
    self_id: int,
    metrics: bool,
    known_bot_sender: bool,
    pallas_ats: frozenset[int],
) -> None:
    """全员同响：仅 @ 定向 / 舰队过滤，跳过 once / federate / shard 抢占。"""
    if known_bot_sender:
        if metrics:
            record_ingress_early_discard("fleet")
        raise IgnoredException("fleet bot message")

    if pallas_ats and self_id not in pallas_ats:
        if metrics:
            record_ingress_early_discard("not_at_target")
        raise IgnoredException("not at-target bot")

    if metrics:
        record_ingress_fanout_bypass()


def known_bot_sender(*, user_id: int, self_id: int) -> bool:
    return (fleet_bot_ids_contains(user_id) and user_id != self_id) or federate_peer_bot_ids_contains(user_id)


async def ingress_notice_preprocess(bot, event) -> None:
    if isinstance(event, NoticeEvent):
        await ingress_notice_gate(bot, event)


async def ingress_group_message_gate(bot, event) -> None:
    if not ingress_gate_active():
        return
    if not isinstance(event, GroupMessageEvent):
        return

    self_id = int(bot.self_id)
    user_id = int(event.user_id)
    metrics = should_record_ingress_metrics(self_id)
    sharding_active = shard_ctx.sharding_active()
    timer = SlowPathTimer(
        "ingress_gate",
        threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_INGRESS_GATE_MS", 20.0),
        log_level="debug",
    )
    outcome = "pass"
    fanout_bypass = False

    try:
        plain = (event.get_plaintext() or "").strip()
        body = plain or event.raw_message
        if user_id == self_id:
            outcome = "self_sent_discard"
            if metrics:
                record_ingress_early_discard("self_sent")
            raise IgnoredException("self-sent bot message")
        sender_is_fleet_bot = known_bot_sender(user_id=user_id, self_id=self_id)
        pallas_ats = pallas_at_targets(event)
        fanout_bypass = ingress_fanout_bypasses_claim(plain)
        if fanout_bypass:
            ingress_fanout_early_exit(
                self_id=self_id,
                metrics=metrics,
                known_bot_sender=sender_is_fleet_bot,
                pallas_ats=pallas_ats,
            )
            outcome = "fanout_bypass"
            return

        if sender_is_fleet_bot:
            outcome = "fleet_discard"
            if metrics:
                record_ingress_early_discard("fleet")
            raise IgnoredException("fleet bot message")

        if not should_process_federate_group_on_current_deployment(int(event.group_id)):
            outcome = "federate_owner_skip"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("federate group owner mismatch")

        at_fleet = message_at_fleet_bot(event)
        ingress_claim_done = False

        if pallas_ats and self_id not in pallas_ats:
            outcome = "not_at_target"
            if metrics:
                record_ingress_early_discard("not_at_target")
            raise IgnoredException("not at-target bot")

        safe_before_host_gates = ingress_once_claim_safe_before_host_gates(
            int(event.group_id),
            plain,
            at_fleet_bot=at_fleet,
        )
        if safe_before_host_gates:
            try:
                for mark in await run_ingress_message_claim(
                    event,
                    body=body,
                    user_id=user_id,
                    self_id=self_id,
                    sharding_active=sharding_active,
                    metrics=metrics,
                ):
                    timer.mark(mark)
                ingress_claim_done = True
            except IngressClaimError as err:
                outcome = err.outcome
                if metrics and err.record_claim_lost:
                    record_ingress_claim(won=False)
                raise IgnoredException(str(err)) from err

        if not hosted_activity_ingress_passes(
            self_id,
            int(event.group_id),
            plain,
            at_fleet_bot=at_fleet,
        ):
            outcome = "spy_host_gate"
            if metrics:
                record_ingress_early_discard("spy_host")
            raise IgnoredException("spy host gate")

        if not await dream_session_ingress_passes(self_id, int(event.group_id)):
            outcome = "dream_host_gate"
            if metrics:
                record_ingress_early_discard("dream_host")
            raise IgnoredException("dream host gate")

        if not ingress_claim_done:
            try:
                for mark in await run_ingress_message_claim(
                    event,
                    body=body,
                    user_id=user_id,
                    self_id=self_id,
                    sharding_active=sharding_active,
                    metrics=metrics,
                ):
                    timer.mark(mark)
            except IngressClaimError as err:
                outcome = err.outcome
                if metrics and err.record_claim_lost:
                    record_ingress_claim(won=False)
                raise IgnoredException(str(err)) from err

        if metrics:
            record_ingress_event()

        if not await claim_federate_group_message_ingress(event, plain=plain, body=body):
            outcome = "federate_lost"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("federate ingress claim lost")
        timer.mark("federate")

        if sharding_active:
            return

        if metrics:
            record_ingress_claim(won=True)
    finally:
        timer.finish(
            outcome=outcome,
            bot_id=self_id,
            group_id=int(event.group_id),
            user_id=user_id,
            fanout_bypass=fanout_bypass,
            sharding=sharding_active,
        )


async def log_ingress_gate_startup() -> None:
    if not ingress_gate_active():
        return
    from pallas.core.platform.federate.config import federate_ingress_active, resolved_federate_id

    n = len(get_fleet_bot_ids())
    mode = "shard" if shard_ctx.sharding_active() else "unified"
    fed = "on" if federate_ingress_active() else "off"
    unified_bypass = "on" if federate_ingress_bypass_unified() else "off"
    logger.debug(
        "[入站门控] mode={} fleet={} federate={} bypass={} id={}",
        mode,
        n,
        fed,
        unified_bypass,
        resolved_federate_id() or "-",
    )
    try:
        start_federate_peer_bot_sync_loop()
        asyncio.create_task(sync_federate_peer_bot_roster(), name="federate_peer_bot_initial_sync")
    except Exception as e:
        logger.debug("federate peer bots: startup sync skipped: {}", e)


def register_ingress_gate_runtime() -> None:
    global _GATE_REGISTERED
    from nonebot import get_driver
    from nonebot.message import event_preprocessor

    from pallas.core.platform.bot_runtime.roles import is_hub_role

    if _GATE_REGISTERED or is_hub_role():
        return

    driver = get_driver()

    @event_preprocessor
    async def ingress_notice_preprocess_hook(bot, event) -> None:
        await ingress_notice_preprocess(bot, event)

    @event_preprocessor
    async def message_scrub_global_hook(bot, event) -> None:
        from nonebot.adapters.onebot.v11 import MessageEvent

        from pallas.product.message_scrub import is_message_scrub_blocked_sync

        if isinstance(event, MessageEvent):
            plain = (event.get_plaintext() or "").strip()
            if is_message_scrub_blocked_sync(plain_text=plain, raw_message=event.raw_message):
                raise IgnoredException("message scrub globally blocked")

    @event_preprocessor
    async def ingress_group_message_gate_hook(bot, event) -> None:
        await ingress_group_message_gate(bot, event)

    @driver.on_startup
    async def ingress_gate_startup_log() -> None:
        await log_ingress_gate_startup()

    _GATE_REGISTERED = True
