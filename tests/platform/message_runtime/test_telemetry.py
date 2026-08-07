from __future__ import annotations

import json

from pallas.core.platform.message_runtime.shadow import ShadowRecord
from pallas.core.platform.message_runtime.telemetry import ExperimentTelemetryWriter


def test_telemetry_persists_failures_without_message_content(tmp_path) -> None:
    writer = ExperimentTelemetryWriter(tmp_path / "message_runtime_experiment.jsonl", agreement_sample_rate=100)
    writer.record(ShadowRecord(ingress_id="ok", timestamp=100, kind="agreement"))
    writer.record(ShadowRecord(ingress_id="bad", timestamp=101, kind="native_error", error_class="RuntimeError"))
    writer.flush()

    rows = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]

    assert rows == [
        {
            "error_class": "RuntimeError",
            "ingress_id": "bad",
            "kind": "native_error",
            "ts": 101,
        }
    ]


def test_telemetry_prunes_expired_records(tmp_path) -> None:
    writer = ExperimentTelemetryWriter(tmp_path / "message_runtime_experiment.jsonl", retention_sec=60)
    writer.record(ShadowRecord(ingress_id="old", timestamp=100, kind="native_error"))
    writer.flush()

    writer.prune(now=161)

    assert not writer.path.exists()
