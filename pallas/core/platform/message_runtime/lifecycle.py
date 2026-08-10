from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.paths import DATA_ROOT

from .experiment import ShadowExperiment
from .handlers import RuntimeHandlerRegistry
from .models import RuntimeMode
from .planner import MessagePlanner
from .runtime import MessageRuntime
from .shadow import ShadowRecord
from .telemetry import ExperimentTelemetryWriter

if TYPE_CHECKING:
    from .models import HandlingOutcome, MessageContext

_shadow_experiment: ShadowExperiment | None = None
_shadow_canary_groups: frozenset[int] = frozenset()
_direct_runtime: MessageRuntime | None = None
_direct_canary_groups: frozenset[int] = frozenset()
_direct_all_groups = False
_telemetry_writer: ExperimentTelemetryWriter | None = None
_shadow_flush_task: asyncio.Task[None] | None = None
_SHADOW_FLUSH_INTERVAL_SEC = 30.0


def message_runtime_experiment_path():
    return DATA_ROOT / "pallas_config" / "message_runtime_experiment.jsonl"


def configure_shadow_experiment(
    *,
    mode: RuntimeMode,
    canary_groups: tuple[int, ...],
    telemetry_enabled: bool,
    retention_hours: int,
    agreement_sample_rate: int,
) -> None:
    global \
        _shadow_experiment, \
        _shadow_canary_groups, \
        _telemetry_writer, \
        _direct_runtime, \
        _direct_canary_groups, \
        _direct_all_groups
    _shadow_experiment = None
    _shadow_canary_groups = frozenset()
    _telemetry_writer = None
    _direct_runtime = None
    _direct_canary_groups = frozenset()
    _direct_all_groups = False
    if mode is RuntimeMode.MATCHER:
        return
    registry = RuntimeHandlerRegistry()
    from packages.drink.direct import DrinkDirectHandler
    from packages.greeting.direct import CallMeDirectHandler
    from packages.help.direct import HelpDirectHandler
    from packages.llm_chat.message_runtime_handler import LlmChatDirectHandler
    from packages.pb_core.direct import ConsoleDirectHandler, PluginsDirectHandler, StatusDirectHandler
    from packages.repeater.message_runtime_handler import RepeaterDirectHandler

    registry.register(DrinkDirectHandler())
    registry.register(CallMeDirectHandler())
    registry.register(HelpDirectHandler())
    registry.register(StatusDirectHandler())
    registry.register(ConsoleDirectHandler())
    registry.register(PluginsDirectHandler())
    registry.register(RepeaterDirectHandler())
    registry.register(LlmChatDirectHandler())
    from .declarations import build_declaration_handlers

    declaration_handlers, diagnostics = build_declaration_handlers()
    for handler in declaration_handlers:
        registry.register(handler)
    for diagnostic in diagnostics:
        logger.warning(
            "MessageRuntime direct registration skipped code={} handler_id={} module={} commands={}",
            diagnostic.code,
            diagnostic.handler_id,
            diagnostic.module,
            diagnostic.commands,
        )
    writer = None
    if telemetry_enabled:
        writer = ExperimentTelemetryWriter(
            message_runtime_experiment_path(),
            agreement_sample_rate=agreement_sample_rate,
            retention_sec=retention_hours * 60 * 60,
        )
        writer.prune()
    _telemetry_writer = writer
    if mode is RuntimeMode.DIRECT:
        _direct_runtime = MessageRuntime(mode, MessagePlanner(registry), registry)
        _direct_canary_groups = frozenset(canary_groups)
        _direct_all_groups = not canary_groups
        return
    if mode is not RuntimeMode.SHADOW:
        return
    _shadow_experiment = ShadowExperiment(MessageRuntime(mode, MessagePlanner(registry), registry), writer)
    _shadow_canary_groups = frozenset(canary_groups)


def shadow_experiment_for_group(group_id: int) -> ShadowExperiment | None:
    if group_id not in _shadow_canary_groups:
        return None
    return _shadow_experiment


def direct_runtime_for_group(group_id: int) -> MessageRuntime | None:
    if not _direct_all_groups and group_id not in _direct_canary_groups:
        return None
    return _direct_runtime


def record_direct_execution(
    context: MessageContext,
    outcome: HandlingOutcome,
    *,
    duration_ms: float,
    timestamp: int | None = None,
) -> None:
    if _telemetry_writer is None:
        return
    if outcome.error_class:
        kind = "direct_error"
    else:
        kind = "direct_handled" if outcome.handled and not outcome.fallback_to_matcher else "direct_fallback"
    _telemetry_writer.record(
        ShadowRecord(
            ingress_id=context.telemetry_fields()["event_id_hash"],
            timestamp=int(time.time()) if timestamp is None else timestamp,
            kind=kind,
            handler_ids=(),
            handler_id=outcome.handler_id,
            fallback_reason=outcome.fallback_reason,
            error_class=outcome.error_class,
            action_count=len(outcome.actions),
            work_job_count=len(outcome.work_jobs) or None,
            cross_worker_action_count=len(outcome.cross_worker_actions) or None,
            deferred_action_count=len(outcome.deferred_actions) or None,
            duration_ms=round(duration_ms, 2),
        )
    )


def flush_shadow_experiment() -> None:
    if _telemetry_writer is not None:
        _telemetry_writer.flush()


async def shadow_experiment_flush_loop() -> None:
    while True:
        await asyncio.sleep(_SHADOW_FLUSH_INTERVAL_SEC)
        await asyncio.to_thread(flush_shadow_experiment)


def start_shadow_experiment_flush_loop() -> None:
    global _shadow_flush_task
    if _telemetry_writer is not None and _shadow_flush_task is None:
        _shadow_flush_task = asyncio.create_task(
            shadow_experiment_flush_loop(),
            name="message_runtime_shadow_flush",
        )


async def stop_shadow_experiment_flush_loop() -> None:
    global _shadow_flush_task
    task = _shadow_flush_task
    _shadow_flush_task = None
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def reset_shadow_experiment_for_tests() -> None:
    global \
        _shadow_experiment, \
        _shadow_canary_groups, \
        _telemetry_writer, \
        _shadow_flush_task, \
        _direct_runtime, \
        _direct_canary_groups, \
        _direct_all_groups
    _shadow_experiment = None
    _shadow_canary_groups = frozenset()
    _telemetry_writer = None
    _shadow_flush_task = None
    _direct_runtime = None
    _direct_canary_groups = frozenset()
    _direct_all_groups = False
