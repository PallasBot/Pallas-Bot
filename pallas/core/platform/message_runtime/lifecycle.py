from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pallas.core.foundation.paths import DATA_ROOT

from .experiment import ShadowExperiment
from .handlers import NativeHandlerRegistry
from .models import RuntimeMode
from .planner import MessagePlanner
from .runtime import MessageRuntime
from .shadow import ShadowRecord
from .telemetry import ExperimentTelemetryWriter

if TYPE_CHECKING:
    from .models import HandlingOutcome, MessageContext

_shadow_experiment: ShadowExperiment | None = None
_shadow_canary_groups: frozenset[int] = frozenset()
_native_runtime: MessageRuntime | None = None
_native_canary_groups: frozenset[int] = frozenset()
_native_all_groups = False
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
        _native_runtime, \
        _native_canary_groups, \
        _native_all_groups
    _shadow_experiment = None
    _shadow_canary_groups = frozenset()
    _telemetry_writer = None
    _native_runtime = None
    _native_canary_groups = frozenset()
    _native_all_groups = False
    if mode is RuntimeMode.LEGACY:
        return
    registry = NativeHandlerRegistry()
    from packages.greeting.native import CallMeNativeHandler
    from packages.help.native import HelpNativeHandler
    from packages.llm_chat.message_runtime_handler import LlmChatNativeHandler
    from packages.pb_core.native import ConsoleNativeHandler, PluginsNativeHandler, StatusNativeHandler
    from packages.repeater.message_runtime_handler import RepeaterNativeHandler

    registry.register(CallMeNativeHandler())
    registry.register(HelpNativeHandler())
    registry.register(StatusNativeHandler())
    registry.register(ConsoleNativeHandler())
    registry.register(PluginsNativeHandler())
    registry.register(RepeaterNativeHandler())
    registry.register(LlmChatNativeHandler())
    writer = None
    if telemetry_enabled:
        writer = ExperimentTelemetryWriter(
            message_runtime_experiment_path(),
            agreement_sample_rate=agreement_sample_rate,
            retention_sec=retention_hours * 60 * 60,
        )
        writer.prune()
    _telemetry_writer = writer
    if mode is RuntimeMode.NATIVE:
        _native_runtime = MessageRuntime(mode, MessagePlanner(registry), registry)
        _native_canary_groups = frozenset(canary_groups)
        _native_all_groups = not canary_groups
        return
    if mode is not RuntimeMode.SHADOW:
        return
    _shadow_experiment = ShadowExperiment(MessageRuntime(mode, MessagePlanner(registry), registry), writer)
    _shadow_canary_groups = frozenset(canary_groups)


def shadow_experiment_for_group(group_id: int) -> ShadowExperiment | None:
    if group_id not in _shadow_canary_groups:
        return None
    return _shadow_experiment


def native_runtime_for_group(group_id: int) -> MessageRuntime | None:
    if not _native_all_groups and group_id not in _native_canary_groups:
        return None
    return _native_runtime


def record_native_execution(
    context: MessageContext,
    outcome: HandlingOutcome,
    *,
    duration_ms: float,
    timestamp: int | None = None,
) -> None:
    if _telemetry_writer is None:
        return
    if outcome.error_class:
        kind = "native_error"
    else:
        kind = "native_handled" if outcome.handled and not outcome.fallback_to_legacy else "native_fallback"
    _telemetry_writer.record(
        ShadowRecord(
            ingress_id=context.ingress_id,
            timestamp=int(time.time()) if timestamp is None else timestamp,
            kind=kind,
            error_class=outcome.error_class,
            action_count=len(outcome.actions),
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
        _native_runtime, \
        _native_canary_groups, \
        _native_all_groups
    _shadow_experiment = None
    _shadow_canary_groups = frozenset()
    _telemetry_writer = None
    _shadow_flush_task = None
    _native_runtime = None
    _native_canary_groups = frozenset()
    _native_all_groups = False
