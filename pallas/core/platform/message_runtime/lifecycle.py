from __future__ import annotations

from pallas.core.foundation.paths import DATA_ROOT

from .experiment import ShadowExperiment
from .handlers import NativeHandlerRegistry
from .models import RuntimeMode
from .planner import MessagePlanner
from .runtime import MessageRuntime
from .telemetry import ExperimentTelemetryWriter

_shadow_experiment: ShadowExperiment | None = None
_shadow_canary_groups: frozenset[int] = frozenset()
_telemetry_writer: ExperimentTelemetryWriter | None = None


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
    global _shadow_experiment, _shadow_canary_groups, _telemetry_writer
    _shadow_experiment = None
    _shadow_canary_groups = frozenset()
    _telemetry_writer = None
    if mode is not RuntimeMode.SHADOW:
        return
    registry = NativeHandlerRegistry()
    writer = None
    if telemetry_enabled:
        writer = ExperimentTelemetryWriter(
            message_runtime_experiment_path(),
            agreement_sample_rate=agreement_sample_rate,
            retention_sec=retention_hours * 60 * 60,
        )
        writer.prune()
    _telemetry_writer = writer
    _shadow_experiment = ShadowExperiment(MessageRuntime(mode, MessagePlanner(registry), registry), writer)
    _shadow_canary_groups = frozenset(canary_groups)


def shadow_experiment_for_group(group_id: int) -> ShadowExperiment | None:
    if group_id not in _shadow_canary_groups:
        return None
    return _shadow_experiment


def flush_shadow_experiment() -> None:
    if _telemetry_writer is not None:
        _telemetry_writer.flush()


def reset_shadow_experiment_for_tests() -> None:
    global _shadow_experiment, _shadow_canary_groups, _telemetry_writer
    _shadow_experiment = None
    _shadow_canary_groups = frozenset()
    _telemetry_writer = None
