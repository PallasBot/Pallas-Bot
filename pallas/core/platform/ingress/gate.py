"""群消息入站预处理与跨机去重。"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, NoticeEvent
from nonebot.exception import IgnoredException

from pallas.core.platform.federate.config import federate_ingress_bypass_unified
from pallas.core.platform.federate.ingress import claim_federate_group_message_ingress
from pallas.core.platform.federate.peer_bots import (
    federate_peer_bot_ids_contains,
    federate_peer_declared_command_plaintext,
    get_federate_peer_bot_ids,
    should_process_federate_group_on_current_deployment,
    should_yield_federate_ingress_for_peer_command,
    start_federate_peer_bot_sync_loop,
    stop_federate_peer_bot_sync_loop,
    sync_federate_peer_bot_roster,
    touch_federate_present_group,
)
from pallas.core.platform.ingress.claim_gate import (
    IngressClaimError,
    ingress_gate_runtime_active,
    run_ingress_message_claim,
)
from pallas.core.platform.ingress.dispatch_stats_logger import start_loop_lag_probe, stop_loop_lag_probe
from pallas.core.platform.ingress.dream_host_gate import dream_session_ingress_passes
from pallas.core.platform.ingress.fanout_bypass import ingress_fanout_bypasses_claim
from pallas.core.platform.ingress.fast_path import (
    ingress_once_claim_safe_before_host_gates,
    run_gate_blocking,
    shutdown_gate_executor,
)
from pallas.core.platform.ingress.group_admin_owner import group_admin_owner_ingress_decision
from pallas.core.platform.ingress.hosted_activity_gate import (
    hosted_activity_claim_is_hosted,
    hosted_activity_ingress_passes,
)
from pallas.core.platform.ingress.matcher_activation import legacy_command_traffic
from pallas.core.platform.ingress.notice_gate import ingress_notice_gate
from pallas.core.platform.multi_bot.at_targets import group_at_qq_ids, message_at_fleet_bot
from pallas.core.platform.multi_bot.fleet import fleet_bot_ids_contains, get_fleet_bot_ids
from pallas.core.platform.multi_bot.group_online_cache import remember_local_group_bot
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
_PRE_SCHEDULER_GATE_COMPLETE: ContextVar[bool] = ContextVar("pre_scheduler_ingress_gate_complete", default=False)
_LOCAL_ONLY_FEDERATE_COMMANDS = frozenset({"#pallas"})


def ingress_gate_active() -> bool:
    return ingress_gate_runtime_active()


def local_only_federate_command(plain: str) -> bool:
    return (plain or "").strip().casefold() in _LOCAL_ONLY_FEDERATE_COMMANDS


def command_lane_traffic(plain: str) -> bool:
    """命令车道判定：本机命令明文，或任一联邦对端显式宣告的命令能力明文。

    对端装了本机没装的命令（如牛牛画画）时，本机也当命令流量进归属环，
    让有能力的一方接手，避免本机把这类消息落入 llm_chat 兜底。
    """
    if legacy_command_traffic(plain, group_only=True):
        return True
    return federate_peer_declared_command_plaintext(plain)


def pallas_at_targets(event: GroupMessageEvent) -> frozenset[int]:
    ats = group_at_qq_ids(event)
    if not ats:
        return frozenset()
    # @ 本部署舰队或联邦对端的牛都算定向点名：对端牛也在群里，被 @ 时
    # 本机不应因「本地 fleet 没有该号」而把消息当闲聊接走。
    bot_ids = get_fleet_bot_ids() | get_federate_peer_bot_ids()
    return ats & bot_ids


@dataclass(frozen=True, slots=True)
class HostGateSnapshot:
    """主持活动门控的两个结论；同一次线程跳转里一起算出，避免重复遍历同一批 spec。"""

    safe_before_host_gates: bool
    alias_target_is_hosted: bool


def host_gate_snapshot(group_id: int, plain: str, *, at_fleet_bot: bool) -> HostGateSnapshot:
    """分片模式下两项判定都会读 coord Redis，调用方须放到 gate 专用线程池执行。"""
    return HostGateSnapshot(
        safe_before_host_gates=ingress_once_claim_safe_before_host_gates(
            group_id,
            plain,
            at_fleet_bot=at_fleet_bot,
        ),
        alias_target_is_hosted=hosted_activity_claim_is_hosted(
            group_id,
            plain,
            at_fleet_bot=at_fleet_bot,
        ),
    )


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
        from pallas.core.platform.multi_bot.group_admin_capability import (
            invalidate_group_admin_capability,
            record_group_admin_notice,
        )

        notice_type = getattr(event, "notice_type", "")
        group_id = int(getattr(event, "group_id", 0) or 0)
        if notice_type in {"group_admin", "set_group_admin"} and group_id:
            bot_id = int(getattr(event, "user_id", 0) or 0)
            if str(bot_id) in get_bots():
                record_group_admin_notice(
                    group_id=group_id,
                    bot_id=bot_id,
                    role="admin"
                    if notice_type == "set_group_admin" or getattr(event, "sub_type", "") == "set"
                    else "member",
                )
        elif notice_type == "group_decrease" and group_id:
            bot_id = int(getattr(event, "user_id", 0) or 0)
            if bot_id == int(bot.self_id):
                invalidate_group_admin_capability(group_id=group_id, bot_id=bot_id)
        await ingress_notice_gate(bot, event)


async def ingress_group_message_gate(bot, event) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    if _PRE_SCHEDULER_GATE_COMPLETE.get():
        return

    self_id = int(bot.self_id)
    remember_local_group_bot(event.group_id, self_id)
    if not ingress_gate_active():
        return
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
        local_only_federate = local_only_federate_command(plain)
        group_admin_decision = await group_admin_owner_ingress_decision(int(event.group_id), self_id, plain)
        if not group_admin_decision.passes:
            outcome = "group_admin_owner_skip"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("group admin owner mismatch")
        if group_admin_decision.fallback_to_fanout:
            ingress_fanout_early_exit(
                self_id=self_id,
                metrics=metrics,
                known_bot_sender=sender_is_fleet_bot,
                pallas_ats=pallas_ats,
            )
            outcome = "group_admin_owner_fallback"
            return
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

        # 收到本群消息即记在场，供命令归属只在「本群有号」的部署间取模。
        touch_federate_present_group(int(event.group_id))

        # 本机无能力、对端显式有：即使本地不认作命令，也不得抢 federate claim。
        if (
            not local_only_federate
            and not pallas_ats
            and should_yield_federate_ingress_for_peer_command(int(event.group_id), plain=plain)
        ):
            outcome = "federate_peer_command_yield"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("federate peer command capability")

        # 仅命令走粘性群归属；闲聊 / @LLM 等 chat 车道只靠 claim，避免热群钉死一台。
        if (
            not local_only_federate
            and not pallas_ats
            and command_lane_traffic(plain)
            and not should_process_federate_group_on_current_deployment(
                int(event.group_id),
                plain=plain,
            )
        ):
            outcome = "federate_owner_skip"
            if metrics:
                record_ingress_early_discard("federate")
            raise IgnoredException("federate group owner mismatch")

        at_fleet = message_at_fleet_bot(event)
        if at_fleet and self_id in pallas_ats:
            event._pallas_llm_at_trigger = True
        ingress_claim_done = False

        if pallas_ats and self_id not in pallas_ats:
            outcome = "not_at_target"
            if metrics:
                record_ingress_early_discard("not_at_target")
            raise IgnoredException("not at-target bot")

        from pallas.core.platform.ingress.alias_route import (
            fleet_bots_matching_plain,
            should_yield_ingress_for_peer_alias,
        )

        alias_matched_bot_ids = fleet_bots_matching_plain(plain)
        host_snapshot = await run_gate_blocking(
            host_gate_snapshot,
            int(event.group_id),
            plain,
            at_fleet_bot=at_fleet,
        )
        safe_before_host_gates = host_snapshot.safe_before_host_gates
        alias_target_is_hosted = host_snapshot.alias_target_is_hosted
        if not alias_target_is_hosted and should_yield_ingress_for_peer_alias(self_id=self_id, plain_text=plain):
            outcome = "peer_alias_yield"
            if metrics:
                record_ingress_early_discard("peer_alias")
            raise IgnoredException("peer alias target")
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

        if not await run_gate_blocking(
            hosted_activity_ingress_passes,
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

        if not local_only_federate and not pallas_ats:
            candidate_capability: str | None = None
            command_lane = command_lane_traffic(plain)
            if alias_target_is_hosted:
                candidate_capability = "hosted_activity"
            elif self_id in alias_matched_bot_ids:
                candidate_capability = "llm_alias"
            elif command_lane:
                candidate_capability = "command"
            candidate_wait = bool(command_lane or alias_matched_bot_ids)
            candidate_wait = candidate_wait or alias_target_is_hosted
            if not await claim_federate_group_message_ingress(
                event,
                plain=plain,
                body=body,
                candidate_capability=candidate_capability,
                candidate_bot_id=self_id if candidate_capability else None,
                candidate_wait=candidate_wait and candidate_capability is None,
                command_traffic=command_lane,
            ):
                outcome = "federate_lost"
                if metrics:
                    record_ingress_early_discard("federate")
                raise IgnoredException("federate ingress claim lost")
            if candidate_capability == "llm_alias":
                event._pallas_llm_alias_hard_trigger = True
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


async def pre_schedule_ingress_group_message_gate(bot, event) -> Token[bool] | None:
    """在 conversation scheduler 前完成群 ingress gate，避免失败副本占用车道。"""
    if not isinstance(event, GroupMessageEvent):
        return None
    await ingress_group_message_gate(bot, event)
    return _PRE_SCHEDULER_GATE_COMPLETE.set(True)


def reset_pre_schedule_ingress_group_message_gate(token: Token[bool] | None) -> None:
    if token is not None:
        _PRE_SCHEDULER_GATE_COMPLETE.reset(token)


async def log_ingress_gate_startup() -> None:
    if not ingress_gate_active():
        return
    from pallas.core.platform.federate.config import federate_ingress_active, resolved_federate_id

    n = len(get_fleet_bot_ids())
    mode = "shard" if shard_ctx.sharding_active() else "unified"
    fed = "on" if federate_ingress_active() else "off"
    unified_bypass = "on" if federate_ingress_bypass_unified() else "off"
    logger.debug(
        "Ingress gate initialized with mode [{}], fleet [{}], federate [{}], bypass [{}], and ID [{}].",
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


async def message_scrub_global_hook(bot, event) -> None:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from pallas.core.perm.check import satisfies_command_permission
    from pallas.product.message_scrub import is_message_scrub_blocked_sync
    from pallas.product.message_scrub.scrub_command import (
        bot_scrub_manage_authorized,
        clear_scrub_command_marker,
        is_bot_scrub_command_id,
        mark_scrub_command,
        match_scrub_command,
    )

    if not isinstance(event, MessageEvent):
        return

    # 每次重置并重验标记：只对「严格合法 + 已授权」的屏蔽词命令做隔离放行。
    # 群命令沿用可配置命令权限；私聊 Bot 级命令额外要求当前 Bot 号主硬条件。
    clear_scrub_command_marker(event)
    match = match_scrub_command(bot, event)
    if match is not None:
        if is_bot_scrub_command_id(match.command_id):
            authorized = await bot_scrub_manage_authorized(bot, event, match.command_id)
        else:
            authorized = await satisfies_command_permission(bot, event, match.command_id)
        if authorized:
            mark_scrub_command(event, match.command_id)
            return

    plain = (event.get_plaintext() or "").strip()
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    raw_self_id = getattr(bot, "self_id", None)
    bot_id = int(raw_self_id) if raw_self_id is not None else None
    if is_message_scrub_blocked_sync(
        plain_text=plain,
        raw_message=event.raw_message,
        group_id=group_id,
        bot_id=bot_id,
    ):
        raise IgnoredException("message scrub globally blocked")


def register_ingress_gate_runtime() -> None:
    global _GATE_REGISTERED
    from nonebot import get_driver
    from nonebot.message import event_preprocessor

    from pallas.core.platform.bot_runtime.roles import is_hub_role
    from pallas.core.platform.ingress.scrub_command_fence import install_scrub_command_fence

    if _GATE_REGISTERED or is_hub_role():
        return

    driver = get_driver()
    install_scrub_command_fence()

    @event_preprocessor
    async def ingress_notice_preprocess_hook(bot, event) -> None:
        await ingress_notice_preprocess(bot, event)

    @event_preprocessor
    async def message_scrub_global_preprocessor(bot, event) -> None:
        await message_scrub_global_hook(bot, event)

    @event_preprocessor
    async def ingress_group_message_gate_hook(bot, event) -> None:
        await ingress_group_message_gate(bot, event)

    @driver.on_startup
    async def ingress_gate_startup_log() -> None:
        await log_ingress_gate_startup()
        start_loop_lag_probe()

    @driver.on_shutdown
    async def federate_peer_sync_shutdown() -> None:
        await stop_loop_lag_probe()
        await stop_federate_peer_bot_sync_loop()
        shutdown_gate_executor()

    _GATE_REGISTERED = True
