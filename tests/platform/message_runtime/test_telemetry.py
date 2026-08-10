from __future__ import annotations

import json

from pallas.core.platform.message_runtime.shadow import ShadowRecord
from pallas.core.platform.message_runtime.telemetry import ExperimentTelemetryWriter


def test_telemetry_persists_failures_without_message_content(tmp_path) -> None:
    writer = ExperimentTelemetryWriter(tmp_path / "message_runtime_experiment.jsonl", agreement_sample_rate=100)
    writer.record(ShadowRecord(ingress_id="ok", timestamp=100, kind="agreement"))
    writer.record(ShadowRecord(ingress_id="bad", timestamp=101, kind="direct_error", error_class="RuntimeError"))
    writer.flush()

    rows = [json.loads(line) for line in writer.path.read_text(encoding="utf-8").splitlines()]

    assert rows == [
        {
            "error_class": "RuntimeError",
            "event_id_hash": "bad",
            "kind": "direct_error",
            "ts": 101,
        }
    ]


def test_telemetry_records_only_non_sensitive_runtime_classification(tmp_path) -> None:
    writer = ExperimentTelemetryWriter(tmp_path / "message_runtime_experiment.jsonl", agreement_sample_rate=1)
    writer.record(
        ShadowRecord(
            ingress_id="hashed-event-id",
            timestamp=100,
            kind="direct_fallback",
            plan_kind="matcher",
            plan_reason="unregistered",
            handler_ids=("repeater.message",),
            error_class="RuntimeError",
        )
    )
    writer.flush()

    row = json.loads(writer.path.read_text(encoding="utf-8"))

    assert row == {
        "event_id_hash": "hashed-event-id",
        "ts": 100,
        "kind": "direct_fallback",
        "plan_kind": "matcher",
        "plan_reason": "unregistered",
        "handler_ids": ["repeater.message"],
        "error_class": "RuntimeError",
    }


def test_telemetry_prune_removes_legacy_rows_with_plain_event_id(tmp_path) -> None:
    path = tmp_path / "message_runtime_experiment.jsonl"
    path.write_text('{"ingress_id":"1:100:3","ts":100,"kind":"native_handled"}\n', encoding="utf-8")
    writer = ExperimentTelemetryWriter(path, retention_sec=60)

    writer.prune(now=101)

    assert not path.exists()


def test_telemetry_prunes_expired_records(tmp_path) -> None:
    writer = ExperimentTelemetryWriter(tmp_path / "message_runtime_experiment.jsonl", retention_sec=60)
    writer.record(ShadowRecord(ingress_id="old", timestamp=100, kind="direct_error"))
    writer.flush()

    writer.prune(now=161)

    assert not writer.path.exists()
