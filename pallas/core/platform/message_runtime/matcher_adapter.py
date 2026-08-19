from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import nonebot.message as nb_message

from pallas.core.platform.ingress.route_index import matcher_module_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Bot, Event


@dataclass(frozen=True, slots=True)
class MatcherDispatchResult:
    selected_matcher_modules: tuple[str, ...]
    acquired_matcher_modules: tuple[str, ...]
    total_selected: int
    total_considered: int
    matchers_run: int
    any_matcher_executed: bool


class MatcherAdapter:
    """Runs the matcher loop with the ingress-owned execution state."""

    def __init__(self, *, batch_size: Callable[[list[type]], list[list[type]]], threshold: Callable[[], int]) -> None:
        self._batch_size = batch_size
        self._threshold = threshold

    async def execute(
        self,
        *,
        bot: Bot,
        event: Event,
        state: dict[Any, Any],
        stack: Any,
        dependency_cache: dict[Any, Any],
        command_traffic: bool,
        llm_command: dict[str, Any] | None,
        chat_degraded: bool,
        direct_matcher_exclude_modules: frozenset[str],
        matcher_pools: dict[int, list[type]],
        matcher_checker: Callable[..., Any],
        select_matchers: Callable[[list[type]], list[type]],
        signal_overload: Callable[[float], None],
    ) -> MatcherDispatchResult:
        total_selected = 0
        total_considered = 0
        matchers_run = 0
        any_matcher_executed = False
        selected_matcher_modules: list[str] = []
        acquired_matcher_modules: list[str] = []
        break_flag = False

        async def run_selected_matcher(matcher: type) -> None:
            nonlocal any_matcher_executed, matchers_run
            result = await matcher_checker(
                matcher,
                bot,
                event,
                state.copy(),
                stack,
                dependency_cache,
                command_traffic=command_traffic,
                synthetic_llm_command=llm_command is not None,
                hard_speak_trigger=bool(
                    matcher_module_key(matcher) == "llm_chat"
                    and (getattr(event, "to_me", False) or getattr(event, "_pallas_llm_alias_hard_trigger", False))
                ),
            )
            if result.acquired:
                matchers_run += 1
                any_matcher_executed = True
                if llm_command is not None:
                    acquired_matcher_modules.append(str(getattr(matcher, "plugin_name", "") or "<unknown>"))

        def handle_stop_propagation(_exc_group) -> None:
            nonlocal break_flag
            break_flag = True
            nb_message.logger.debug("Stop event propagation")

        for priority in sorted(matcher_pools.keys()):
            if break_flag:
                break
            if not (priority_matchers := matcher_pools[priority]):
                continue

            selected = select_matchers(priority_matchers)
            if llm_command is not None:
                selected = [item for item in selected if matcher_module_key(item) in llm_command["route_modules"]]
            elif chat_degraded:
                selected = [
                    item for item in selected if matcher_module_key(item) in frozenset({"repeater", "llm_chat"})
                ]
            if direct_matcher_exclude_modules:
                selected = [item for item in selected if matcher_module_key(item) not in direct_matcher_exclude_modules]
            if not selected:
                continue

            selected_matcher_modules.extend(str(getattr(item, "plugin_name", "") or "<unknown>") for item in selected)
            total_considered += len(priority_matchers)
            total_selected += len(selected)
            # 非群消息（私聊/通知等）select_matchers 会返回全部 matcher，累加值不代表真实派发压力，
            # 只对群消息用 total_selected 判断过载，避免私聊流量误触发全局降质。
            if getattr(event, "group_id", None) is not None and total_selected > self._threshold():
                signal_overload(3.0)

            with nb_message.catch({
                nb_message.StopPropagation: handle_stop_propagation,
                Exception: nb_message._handle_exception("<r><bg #f8bbd0>Error when checking Matcher.</bg #f8bbd0></r>"),
            }):
                for batch in self._batch_size(selected):
                    if break_flag:
                        break
                    async with nb_message.anyio.create_task_group() as task_group:
                        for matcher in batch:
                            task_group.start_soon(nb_message.run_coro_with_shield, run_selected_matcher(matcher))

        return MatcherDispatchResult(
            selected_matcher_modules=tuple(selected_matcher_modules),
            acquired_matcher_modules=tuple(acquired_matcher_modules),
            total_selected=total_selected,
            total_considered=total_considered,
            matchers_run=matchers_run,
            any_matcher_executed=any_matcher_executed,
        )
