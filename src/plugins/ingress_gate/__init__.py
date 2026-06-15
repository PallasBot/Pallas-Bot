"""群消息入站预处理器：fleet 识别、@ 定向、联邦/跨 Bot claim。"""

from __future__ import annotations

import asyncio

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.platform.federate.config import federate_ingress_bypass_unified
from src.platform.federate.ingress import claim_federate_group_message_ingress
from src.platform.federate.peer_bots import (
    federate_peer_bot_ids_contains,
    should_process_federate_group_on_current_deployment,
    start_federate_peer_bot_sync_loop,
    sync_federate_peer_bot_roster,
)
from src.platform.ingress.claim_gate import (
    IngressClaimError,
    ingress_gate_runtime_active,
    shard_worker_ingress_claims,
    unified_ingress_once_claim,
)
from src.platform.ingress.dream_host_gate import dream_session_ingress_passes
from src.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim
from src.platform.ingress.hosted_activity_gate import (
    hosted_activity_ingress_passes,
)
from src.platform.multi_bot.at_targets import group_at_qq_ids, message_at_fleet_bot
from src.platform.multi_bot.fleet import fleet_bot_ids_contains, get_fleet_bot_ids
from src.platform.observability import SlowPathTimer, slow_path_threshold_ms
from src.platform.shard import context as shard_ctx
from src.platform.shard.ingress_metrics import (
    record_ingress_claim,
    record_ingress_early_discard,
    record_ingress_event,
    record_ingress_fanout_bypass,
    should_record_ingress_metrics,
)

driver = get_driver()

__plugin_meta__ = PluginMetadata(
    name="入站网关",
    description=(
        "群消息预处理：牛牛舰队识别、@ 定向、联邦与跨 Bot claim；分片 worker 另含跨片 claim 与问候/报数 fanout。"
    ),
    usage="（内部）无用户命令；unified / worker 启动时自动注册 event_preprocessor。",
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "help_audience": "maintainer",
    },
)


def ingress_gate_active() -> bool:
    return ingress_gate_runtime_active()


def pallas_at_targets(event: GroupMessageEvent) -> frozenset[int]:
    ats = group_at_qq_ids(event)
    if not ats:
        return frozenset()
    return ats & get_fleet_bot_ids()


def _ingress_fanout_early_exit(
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


def _known_bot_sender(*, user_id: int, self_id: int) -> bool:
    return (fleet_bot_ids_contains(user_id) and user_id != self_id) or federate_peer_bot_ids_contains(user_id)


@event_preprocessor
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
        known_bot_sender = _known_bot_sender(user_id=user_id, self_id=self_id)
        pallas_ats = pallas_at_targets(event)
        fanout_bypass = ingress_fanout_bypasses_claim(plain)
        if fanout_bypass:
            _ingress_fanout_early_exit(
                self_id=self_id,
                metrics=metrics,
                known_bot_sender=known_bot_sender,
                pallas_ats=pallas_ats,
            )
            outcome = "fanout_bypass"
            return

        if known_bot_sender:
            outcome = "fleet_discard"
            if metrics:
                record_ingress_early_discard("fleet")
            raise IgnoredException("fleet bot message")

        if not should_process_federate_group_on_current_deployment(int(event.group_id)):
            outcome = "federate_owner_skip"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("federate group owner mismatch")

        if not hosted_activity_ingress_passes(
            self_id,
            int(event.group_id),
            plain,
            at_fleet_bot=message_at_fleet_bot(event),
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

        try:
            await unified_ingress_once_claim(event, body=body, user_id=user_id)
            if not sharding_active:
                timer.mark("once_claim")
        except IngressClaimError as err:
            outcome = err.outcome
            if metrics and err.record_claim_lost:
                record_ingress_claim(won=False)
            raise IgnoredException(str(err)) from err

        if metrics:
            record_ingress_event()

        if pallas_ats and self_id not in pallas_ats:
            outcome = "not_at_target"
            if metrics:
                record_ingress_early_discard("not_at_target")
            raise IgnoredException("not at-target bot")

        if not await claim_federate_group_message_ingress(event, plain=plain, body=body):
            outcome = "federate_lost"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("federate ingress claim lost")
        timer.mark("federate")

        if sharding_active:
            try:
                for mark in await shard_worker_ingress_claims(
                    event,
                    body=body,
                    user_id=user_id,
                    self_id=self_id,
                ):
                    timer.mark(mark)
            except IngressClaimError as err:
                outcome = err.outcome
                if metrics and err.record_claim_lost:
                    record_ingress_claim(won=False)
                raise IgnoredException(str(err)) from err
            if metrics:
                record_ingress_claim(won=True)
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


@driver.on_startup
async def _log_ingress_gate() -> None:
    if not ingress_gate_active():
        return
    from src.platform.federate.config import federate_ingress_active, resolved_federate_id

    n = len(get_fleet_bot_ids())
    mode = "shard" if shard_ctx.sharding_active() else "unified"
    fed = "on" if federate_ingress_active() else "off"
    unified_bypass = "on" if federate_ingress_bypass_unified() else "off"
    logger.info(
        "ingress_gate: active mode={} fleet_bots={} federate_ingress={} unified_bypass={} federate_id={}",
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
