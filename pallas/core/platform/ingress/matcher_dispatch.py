from __future__ import annotations

import contextlib
import importlib
import time
from typing import TYPE_CHECKING, Any

import nonebot.message as nb_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import IgnoredException
from nonebot.log import logger
from nonebot.matcher import matchers

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ingress.conversation_scheduler import (
    conversation_scheduler_enabled,
    submit_conversation_event,
)
from pallas.core.platform.ingress.dispatch_lanes import (
    check_and_run_matcher_with_lane,
    install_dispatch_lanes,
    uninstall_dispatch_lanes,
)
from pallas.core.platform.ingress.dispatch_metrics import (
    record_chatter_overload_degraded,
    record_chatter_overload_dropped,
    record_group_message_ingress,
    record_preprocessor_dropped,
    record_route_index_decision,
)
from pallas.core.platform.ingress.fleet_dispatch_scale import scaled_dispatch_int
from pallas.core.platform.ingress.matcher_activation import (
    clear_event_dispatch_text_cache,
    event_command_traffic,
    resolve_route_for_event,
    select_priority_matchers,
)
from pallas.core.platform.ingress.message_load import (
    is_overloaded,
    mark_activity,
    mark_chat_degraded,
    reset_chat_degraded,
    signal_overload,
)
from pallas.core.platform.ingress.route_candidate_metrics import record_route_candidate
from pallas.core.platform.ingress.route_index import RouteResolution, matcher_module_key
from pallas.core.platform.message_runtime.legacy_adapter import LegacyMatcherAdapter
from pallas.core.platform.message_runtime.lifecycle import (
    native_runtime_for_group,
    record_native_execution,
    shadow_experiment_for_group,
)
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext
from pallas.core.platform.message_runtime.shadow import LegacyExecution
from pallas.core.platform.multi_bot.dedup import needs_group_host_bot_gate

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

_PATCHED = False
_ORIGINAL_HANDLE_EVENT = None
_ORIGINAL_ADAPTER_HANDLE_EVENTS: dict[object, object] = {}
_OVERLOAD_SELECTED_THRESHOLD = 24
_MATCHER_DISPATCH_BATCH = 8
_CORE_CHATTER_MODULES = frozenset({"repeater", "llm_chat"})


def matcher_dispatch_enabled() -> bool:
    raw = repo_env_raw_value("PALLAS_MATCHER_DISPATCH_ENABLED")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


def overload_selected_threshold() -> int:
    raw = repo_env_raw_value("PALLAS_MATCHER_DISPATCH_OVERLOAD_THRESHOLD")
    if raw is None:
        return scaled_dispatch_int(_OVERLOAD_SELECTED_THRESHOLD, per_bot=1, cap=48)
    try:
        return max(1, int(str(raw).strip()))
    except ValueError:
        return scaled_dispatch_int(_OVERLOAD_SELECTED_THRESHOLD, per_bot=1, cap=48)


def matcher_dispatch_batch_size() -> int:
    raw = repo_env_raw_value("PALLAS_MATCHER_DISPATCH_BATCH")
    if raw is None:
        return scaled_dispatch_int(_MATCHER_DISPATCH_BATCH, per_bot=1, cap=16)
    try:
        return max(1, int(str(raw).strip()))
    except ValueError:
        return scaled_dispatch_int(_MATCHER_DISPATCH_BATCH, per_bot=1, cap=16)


def chat_drop_on_overload_enabled() -> bool:
    """过载时是否整段跳过闲聊 matcher。

    默认关闭：聊天 Bot 高峰应降质接话（停 learn / LLM），而不是突然哑巴。
    需要极端保命令吞吐时可显式打开。
    """
    raw = repo_env_raw_value("PALLAS_INGRESS_CHAT_DROP_ON_OVERLOAD")
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    return False


def matcher_dispatch_batches(selected_matchers: list[type]) -> list[list[type]]:
    batch_size = matcher_dispatch_batch_size()
    return [selected_matchers[i : i + batch_size] for i in range(0, len(selected_matchers), batch_size)]


_legacy_matcher_adapter = LegacyMatcherAdapter(
    batch_size=matcher_dispatch_batches,
    threshold=overload_selected_threshold,
)


def synthetic_llm_command_context(event: Event) -> dict[str, Any] | None:
    raw = getattr(event, "_pallas_llm_command_context", None)
    if not isinstance(raw, dict):
        return None
    command_id = str(raw.get("command_id") or "").strip()
    if not command_id:
        return None
    return {
        "command_id": command_id,
        "source_segment_types": [str(item) for item in raw.get("source_segment_types") or []],
    }


def matcher_log_name(matcher: type) -> str:
    return str(getattr(matcher, "plugin_name", "") or "<unknown>")


def message_runtime_context(
    bot: Bot,
    event: GroupMessageEvent,
    *,
    command_traffic: bool,
    resolution: RouteResolution | None,
) -> MessageContext:
    bot_id = int(bot.self_id)
    group_id = int(event.group_id)
    message_id = int(getattr(event, "message_id", 0) or 0)
    plain_text = str(event.get_plaintext() or "")
    raw_text = str(getattr(event, "raw_message", "") or "")
    return MessageContext(
        ingress_id=f"{bot_id}:{group_id}:{message_id}",
        bot_id=bot_id,
        group_id=group_id,
        message_id=message_id,
        plain_text=plain_text,
        raw_text=raw_text,
        is_to_me=bool(getattr(event, "to_me", False) or getattr(event, "_pallas_llm_alias_hard_trigger", False)),
        command_traffic=command_traffic,
        route_modules=resolution.matched_modules if resolution is not None else frozenset(),
    )


def record_message_runtime_shadow(
    experiment: Any,
    context: MessageContext,
    plan: Any,
    *,
    handler_ids: tuple[str, ...],
    handled: bool,
) -> None:
    try:
        experiment.record_legacy(
            context,
            plan,
            LegacyExecution(handler_ids=handler_ids, handled=handled, visible_actions=0),
            timestamp=int(time.time()),
        )
    except Exception:
        logger.exception("MessageRuntime shadow record failed")


def select_synthetic_llm_command_matchers(selected_matchers: list[type], resolution: RouteResolution) -> list[type]:
    """合成命令仅派发到其路由目标，避免无关 blocker 占满执行通道。"""
    return [matcher for matcher in selected_matchers if matcher_module_key(matcher) in resolution.matched_modules]


def select_overload_chatter_matchers(selected_matchers: list[type]) -> list[type]:
    """过载时仍保留核心闲聊的接话判断，暂缓其他被动能力。"""
    return [matcher for matcher in selected_matchers if matcher_module_key(matcher) in _CORE_CHATTER_MODULES]


def exclude_native_matchers(selected_matchers: list[type], modules: frozenset[str]) -> list[type]:
    if not modules:
        return selected_matchers
    return [matcher for matcher in selected_matchers if matcher_module_key(matcher) not in modules]


def record_route_candidate_safe(
    *,
    command_traffic: bool,
    resolution: RouteResolution | None,
    duration_ms: float,
    matchers_considered: int,
    matchers_selected: int,
    matchers_run: int,
    native_outcome: HandlingOutcome | None,
    legacy_handled: bool,
) -> None:
    if not command_traffic:
        return
    native_status = None
    visible_actions = None
    effect_actions = None
    if native_outcome is not None:
        if native_outcome.error_class:
            native_status = "native_error"
        elif native_outcome.fallback_to_legacy:
            native_status = "native_fallback"
        elif native_outcome.handled:
            native_status = "native_handled"
        visible_actions = len(native_outcome.actions)
        effect_actions = (
            visible_actions
            + len(native_outcome.work_jobs)
            + len(native_outcome.deferred_actions)
            + len(native_outcome.cross_worker_actions)
            + len(native_outcome.llm_select_actions)
        )
    try:
        record_route_candidate(
            route_modules=resolution.matched_modules if resolution is not None else frozenset(),
            index_hit=bool(resolution and resolution.index_hit),
            route_fallback=not bool(resolution and resolution.index_hit),
            matchers_considered=matchers_considered,
            matchers_selected=matchers_selected,
            matchers_run=matchers_run,
            native_outcome=native_status,
            legacy_handled=legacy_handled,
            native_visible_actions=visible_actions,
            native_effect_actions=effect_actions,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.exception("Route candidate metrics record failed")


async def pre_schedule_ingress_group_message_gate(bot: Bot, event: Event):
    from pallas.core.platform.ingress.gate import pre_schedule_ingress_group_message_gate as run_gate

    return await run_gate(bot, event)


def reset_pre_schedule_ingress_group_message_gate(token) -> None:
    from pallas.core.platform.ingress.gate import reset_pre_schedule_ingress_group_message_gate as reset_gate

    reset_gate(token)


async def patched_handle_event(bot: Bot, event: Event) -> None:
    if isinstance(event, GroupMessageEvent) and conversation_scheduler_enabled():
        try:
            gate_token = await pre_schedule_ingress_group_message_gate(bot, event)
        except IgnoredException:
            return
        try:
            await submit_conversation_event(bot, event, lambda: patched_handle_event_now(bot, event))
        finally:
            reset_pre_schedule_ingress_group_message_gate(gate_token)
        return
    await patched_handle_event_now(bot, event)


async def patched_handle_event_now(bot: Bot, event: Event) -> None:
    from pallas.core.foundation.logging import compact_inbound_event_log, inbound_event_log_as_debug

    ingress_started = time.perf_counter()
    mark_activity()
    show_log = True
    log_msg = f" {nb_message.escape_tag(bot.type)} {nb_message.escape_tag(bot.self_id)} | "
    try:
        # 群消息正文可能含 `<le>` 等伪标签；colors=True 时必须 escape，否则整条事件处理失败
        log_msg += nb_message.escape_tag(compact_inbound_event_log(event.get_log_string()))
    except nb_message.NoLogException:
        show_log = False
    if show_log:
        log = nb_message.logger.opt(colors=True)
        event_type = ""
        with contextlib.suppress(Exception):
            event_type = str(event.get_type() or "")
        if inbound_event_log_as_debug(event_type):
            log.debug(log_msg)
        else:
            log.success(log_msg)

    state: dict[Any, Any] = {}
    dependency_cache: dict[Any, Any] = {}
    llm_command = synthetic_llm_command_context(event)
    selected_matcher_modules: list[str] = []
    acquired_matcher_modules: list[str] = []

    try:
        async with nb_message.AsyncExitStack() as stack:
            if not await nb_message._apply_event_preprocessors(
                bot=bot,
                event=event,
                state=state,
                stack=stack,
                dependency_cache=dependency_cache,
            ):
                if isinstance(event, GroupMessageEvent):
                    record_preprocessor_dropped()
                return

            with contextlib.suppress(Exception):
                nb_message.TrieRule.get_value(bot, event, state)

            apply_dispatch = isinstance(event, GroupMessageEvent)
            resolution = resolve_route_for_event(event) if apply_dispatch else None
            command_traffic = event_command_traffic(event, state, resolution=resolution) if apply_dispatch else True
            shadow_experiment = None
            shadow_context = None
            shadow_plan = None
            if apply_dispatch:
                shadow_experiment = shadow_experiment_for_group(int(getattr(event, "group_id", 0) or 0))
                if shadow_experiment is not None:
                    try:
                        shadow_context = message_runtime_context(
                            bot,
                            event,
                            command_traffic=command_traffic,
                            resolution=resolution,
                        )
                        shadow_plan = await shadow_experiment.plan(shadow_context)
                    except Exception:
                        logger.exception("MessageRuntime shadow plan failed")
                        shadow_experiment = None
                        shadow_context = None
            if apply_dispatch:
                native_legacy_exclude_modules = frozenset()
                native_outcome = None
                native_runtime = native_runtime_for_group(int(getattr(event, "group_id", 0) or 0))
                if native_runtime is not None:
                    try:
                        native_context = message_runtime_context(
                            bot,
                            event,
                            command_traffic=command_traffic,
                            resolution=resolution,
                        )
                        native_started = time.perf_counter()
                        native_outcome = await native_runtime.execute_and_commit(native_context, bot=bot, event=event)
                        record_native_execution(
                            native_context,
                            native_outcome,
                            duration_ms=(time.perf_counter() - native_started) * 1000.0,
                        )
                    except Exception:
                        logger.exception("MessageRuntime native execution failed")
                    else:
                        if native_outcome.handled and not native_outcome.fallback_to_legacy:
                            if not native_outcome.continue_legacy:
                                record_group_message_ingress(
                                    duration_ms=(time.perf_counter() - ingress_started) * 1000.0,
                                    command_traffic=command_traffic,
                                    matchers_considered=0,
                                    matchers_selected=0,
                                    matchers_run=0,
                                )
                                record_route_candidate_safe(
                                    command_traffic=command_traffic,
                                    resolution=resolution,
                                    duration_ms=(time.perf_counter() - ingress_started) * 1000.0,
                                    matchers_considered=0,
                                    matchers_selected=0,
                                    matchers_run=0,
                                    native_outcome=native_outcome,
                                    legacy_handled=False,
                                )
                                await nb_message._apply_event_postprocessors(bot, event, state, stack, dependency_cache)
                                return
                            native_legacy_exclude_modules = native_outcome.legacy_exclude_modules
            else:
                native_legacy_exclude_modules = frozenset()
            if apply_dispatch and resolution is not None:
                record_route_index_decision(
                    index_hit=resolution.index_hit,
                    fallback=command_traffic and not resolution.index_hit,
                )
            chat_degraded_token = None
            if apply_dispatch and not command_traffic and is_overloaded():
                if chat_drop_on_overload_enabled():
                    record_chatter_overload_dropped()
                    record_group_message_ingress(
                        duration_ms=(time.perf_counter() - ingress_started) * 1000.0,
                        command_traffic=False,
                        matchers_considered=0,
                        matchers_selected=0,
                        matchers_run=0,
                    )
                    if shadow_experiment is not None and shadow_context is not None and shadow_plan is not None:
                        record_message_runtime_shadow(
                            shadow_experiment,
                            shadow_context,
                            shadow_plan,
                            handler_ids=(),
                            handled=False,
                        )
                    await nb_message._apply_event_postprocessors(bot, event, state, stack, dependency_cache)
                    return
                # 默认：继续跑闲聊 matcher，标记降质（停附属、保本地接话）
                record_chatter_overload_degraded()
                chat_degraded_token = mark_chat_degraded(True)

            try:
                total_selected = 0
                total_considered = 0
                matchers_run = 0
                any_matcher_executed = False
                legacy_matcher_modules: list[str] = []

                if show_log:
                    nb_message.logger.debug("Checking for matchers completed")

                def select_legacy_matchers(priority_matchers: list[type]) -> list[type]:
                    selected = (
                        select_priority_matchers(
                            priority_matchers,
                            command_traffic=command_traffic,
                            resolution=resolution,
                            event=event,
                        )
                        if apply_dispatch
                        else priority_matchers
                    )
                    if llm_command is not None and resolution is not None:
                        selected = select_synthetic_llm_command_matchers(selected, resolution)
                    elif chat_degraded_token is not None:
                        selected = select_overload_chatter_matchers(selected)
                    return exclude_native_matchers(selected, native_legacy_exclude_modules)

                legacy_result = await _legacy_matcher_adapter.execute(
                    bot=bot,
                    event=event,
                    state=state,
                    stack=stack,
                    dependency_cache=dependency_cache,
                    command_traffic=command_traffic,
                    llm_command=(
                        dict(llm_command, route_modules=resolution.matched_modules)
                        if llm_command is not None and resolution is not None
                        else None
                    ),
                    chat_degraded=chat_degraded_token is not None,
                    native_legacy_exclude_modules=native_legacy_exclude_modules,
                    matcher_pools=matchers,
                    matcher_checker=check_and_run_matcher_with_lane,
                    select_matchers=select_legacy_matchers,
                    signal_overload=signal_overload,
                )
                total_selected = legacy_result.total_selected
                total_considered = legacy_result.total_considered
                matchers_run = legacy_result.matchers_run
                any_matcher_executed = legacy_result.any_matcher_executed
                legacy_matcher_modules.extend(legacy_result.selected_matcher_modules)
                selected_matcher_modules.extend(legacy_result.selected_matcher_modules)
                acquired_matcher_modules.extend(legacy_result.acquired_matcher_modules)

                if apply_dispatch:
                    ingress_duration_ms = (time.perf_counter() - ingress_started) * 1000.0
                    record_group_message_ingress(
                        duration_ms=ingress_duration_ms,
                        command_traffic=command_traffic,
                        matchers_considered=total_considered,
                        matchers_selected=total_selected,
                        matchers_run=matchers_run,
                    )
                    record_route_candidate_safe(
                        command_traffic=command_traffic,
                        resolution=resolution,
                        duration_ms=ingress_duration_ms,
                        matchers_considered=total_considered,
                        matchers_selected=total_selected,
                        matchers_run=matchers_run,
                        native_outcome=native_outcome,
                        legacy_handled=any_matcher_executed,
                    )
                if llm_command is not None:
                    logger.info(
                        "LLM 合成命令调度 command={} source_segment_types={} selected_matchers={} acquired_matchers={}",
                        llm_command["command_id"],
                        llm_command["source_segment_types"],
                        selected_matcher_modules,
                        acquired_matcher_modules,
                    )
                if shadow_experiment is not None and shadow_context is not None and shadow_plan is not None:
                    record_message_runtime_shadow(
                        shadow_experiment,
                        shadow_context,
                        shadow_plan,
                        handler_ids=tuple(sorted(set(legacy_matcher_modules))),
                        handled=any_matcher_executed,
                    )

                await nb_message._apply_event_postprocessors(bot, event, state, stack, dependency_cache)
            finally:
                if chat_degraded_token is not None:
                    reset_chat_degraded(chat_degraded_token)
    finally:
        clear_event_dispatch_text_cache()


def install_matcher_dispatch() -> None:
    global _PATCHED, _ORIGINAL_HANDLE_EVENT
    if _PATCHED or not matcher_dispatch_enabled():
        return
    install_dispatch_lanes()
    _ORIGINAL_HANDLE_EVENT = nb_message.handle_event

    async def wrapped(bot: Bot, event: Event) -> None:
        await patched_handle_event(bot, event)

    nb_message.handle_event = wrapped  # type: ignore[assignment]
    for module_name in ("nonebot.adapters.onebot.v11.bot", "nonebot.adapters.onebot.v12.bot"):
        with contextlib.suppress(Exception):
            module = importlib.import_module(module_name)
            current = getattr(module, "handle_event", None)
            if current is not None:
                _ORIGINAL_ADAPTER_HANDLE_EVENTS[module] = current
                module.handle_event = wrapped  # noqa: B010

    _PATCHED = True
    logger.debug(
        "[消息预筛] overload_threshold={} multi_bot={} adapter_patches={}",
        overload_selected_threshold(),
        needs_group_host_bot_gate(),
        len(_ORIGINAL_ADAPTER_HANDLE_EVENTS),
    )


def uninstall_matcher_dispatch() -> None:
    global _PATCHED, _ORIGINAL_HANDLE_EVENT
    if not _PATCHED or _ORIGINAL_HANDLE_EVENT is None:
        return
    nb_message.handle_event = _ORIGINAL_HANDLE_EVENT  # type: ignore[assignment]
    for module, original in list(_ORIGINAL_ADAPTER_HANDLE_EVENTS.items()):
        with contextlib.suppress(Exception):
            module.handle_event = original  # noqa: B010
    _ORIGINAL_ADAPTER_HANDLE_EVENTS.clear()
    _PATCHED = False
    _ORIGINAL_HANDLE_EVENT = None
    uninstall_dispatch_lanes()


def matcher_dispatch_installed() -> bool:
    return _PATCHED
