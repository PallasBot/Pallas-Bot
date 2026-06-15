from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any

import nonebot.message as nb_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger
from nonebot.matcher import matchers

from src.foundation.config.repo_settings import repo_env_raw_value
from src.platform.ingress.dispatch_lanes import (
    check_and_run_matcher_with_lane,
    install_dispatch_lanes,
    uninstall_dispatch_lanes,
)
from src.platform.ingress.dispatch_metrics import record_group_message_ingress, record_preprocessor_dropped
from src.platform.ingress.matcher_activation import (
    event_command_traffic,
    resolve_route_for_event,
    select_priority_matchers,
)
from src.platform.ingress.message_load import mark_activity, signal_overload
from src.platform.multi_bot.dedup import needs_group_host_bot_gate

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

_PATCHED = False
_ORIGINAL_HANDLE_EVENT = None
_OVERLOAD_SELECTED_THRESHOLD = 24


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
        return _OVERLOAD_SELECTED_THRESHOLD
    try:
        return max(1, int(str(raw).strip()))
    except ValueError:
        return _OVERLOAD_SELECTED_THRESHOLD


async def patched_handle_event(bot: Bot, event: Event) -> None:
    ingress_started = time.perf_counter()
    mark_activity()
    show_log = True
    log_msg = f" {nb_message.escape_tag(bot.type)} {nb_message.escape_tag(bot.self_id)} | "
    try:
        log_msg += event.get_log_string()
    except nb_message.NoLogException:
        show_log = False
    if show_log:
        nb_message.logger.opt(colors=True).success(log_msg)

    state: dict[Any, Any] = {}
    dependency_cache: dict[Any, Any] = {}

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
        threshold = overload_selected_threshold()
        total_selected = 0
        total_considered = 0
        matchers_run = 0

        break_flag = False
        lane_busy_sent = False
        lane_busy_lock = nb_message.anyio.Lock()

        async def run_selected_matcher(matcher) -> None:
            nonlocal lane_busy_sent, matchers_run
            matchers_run += 1
            async with lane_busy_lock:
                already_sent = lane_busy_sent
            sent = await check_and_run_matcher_with_lane(
                matcher,
                bot,
                event,
                state.copy(),
                stack,
                dependency_cache,
                command_traffic=command_traffic,
                busy_reply_sent=already_sent,
            )
            if sent:
                async with lane_busy_lock:
                    lane_busy_sent = True

        def handle_stop_propagation(_exc_group) -> None:
            nonlocal break_flag
            break_flag = True
            nb_message.logger.debug("Stop event propagation")

        for priority in sorted(matchers.keys()):
            if break_flag:
                break

            if show_log:
                nb_message.logger.debug("Checking for matchers in priority {}...", priority)

            if not (priority_matchers := matchers[priority]):
                continue

            selected_matchers = (
                select_priority_matchers(
                    priority_matchers,
                    command_traffic=command_traffic,
                    resolution=resolution,
                )
                if apply_dispatch
                else priority_matchers
            )
            if not selected_matchers:
                continue

            total_considered += len(priority_matchers)
            total_selected += len(selected_matchers)
            if total_selected > threshold:
                signal_overload(3.0)

            with nb_message.catch({
                nb_message.StopPropagation: handle_stop_propagation,
                Exception: nb_message._handle_exception("<r><bg #f8bbd0>Error when checking Matcher.</bg #f8bbd0></r>"),
            }):
                async with nb_message.anyio.create_task_group() as tg:
                    for matcher in selected_matchers:
                        tg.start_soon(nb_message.run_coro_with_shield, run_selected_matcher(matcher))

        if show_log:
            nb_message.logger.debug("Checking for matchers completed")

        if apply_dispatch:
            record_group_message_ingress(
                duration_ms=(time.perf_counter() - ingress_started) * 1000.0,
                command_traffic=command_traffic,
                matchers_considered=total_considered,
                matchers_selected=total_selected,
                matchers_run=matchers_run,
            )

        await nb_message._apply_event_postprocessors(bot, event, state, stack, dependency_cache)


def install_matcher_dispatch() -> None:
    global _PATCHED, _ORIGINAL_HANDLE_EVENT
    if _PATCHED or not matcher_dispatch_enabled():
        return
    install_dispatch_lanes()
    _ORIGINAL_HANDLE_EVENT = nb_message.handle_event

    async def wrapped(bot: Bot, event: Event) -> None:
        await patched_handle_event(bot, event)

    nb_message.handle_event = wrapped  # type: ignore[assignment]
    _PATCHED = True
    logger.info(
        "matcher_dispatch: installed overload_threshold={} multi_bot={}",
        overload_selected_threshold(),
        needs_group_host_bot_gate(),
    )


def uninstall_matcher_dispatch() -> None:
    global _PATCHED, _ORIGINAL_HANDLE_EVENT
    if not _PATCHED or _ORIGINAL_HANDLE_EVENT is None:
        return
    nb_message.handle_event = _ORIGINAL_HANDLE_EVENT  # type: ignore[assignment]
    _PATCHED = False
    _ORIGINAL_HANDLE_EVENT = None
    uninstall_dispatch_lanes()


def matcher_dispatch_installed() -> bool:
    return _PATCHED
