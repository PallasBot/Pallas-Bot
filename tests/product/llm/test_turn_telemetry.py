from __future__ import annotations

import json
import sys

import pallas.product.llm.turn_telemetry as turn_telemetry
from pallas.product.llm.turn_telemetry import (
    TurnTelemetryWriter,
    build_turn_event,
    classify_text_shape,
    hash_value,
)


def test_classify_text_shape_covers_short_noise_boundaries() -> None:
    assert classify_text_shape("")["len_bucket"] == "0"
    assert classify_text_shape("😄")["emoji_only"] is True
    assert classify_text_shape("???")["punctuation_only"] is True
    assert classify_text_shape("666")["numeric_only"] is True
    assert classify_text_shape("今天好闲")["short_social"] is True
    assert classify_text_shape("这个怎么弄")["reply_obligation"] is True


def test_hash_value_is_stable_for_one_key_and_changes_with_key() -> None:
    first = hash_value("message", key=b"key-a")
    same = hash_value("message", key=b"key-a")
    other = hash_value("message", key=b"key-b")
    assert first == same
    assert first != other
    assert "message" not in str(first)


def test_build_event_does_not_accept_arbitrary_payload_fields() -> None:
    event = build_turn_event(
        turn_id="turn-1",
        stage="reply_gate",
        decision="skip",
        reason="noise",
        text="???",
        context_assembly_ms=18,
        delivery_latency_ms=30,
        extra={"prompt": "must not persist"},
    )
    assert "prompt" not in event
    assert "text" not in event
    assert event["shape"]["punctuation_only"] is True
    assert event["context_assembly_ms"] == 18
    assert event["delivery_latency_ms"] == 30


def test_writer_emits_one_privacy_safe_json_line(tmp_path) -> None:
    writer = TurnTelemetryWriter(tmp_path, instance_id="test")
    writer.emit(
        build_turn_event(
            turn_id="turn-1",
            stage="ingress",
            decision="proceed",
            text="今天好闲",
            message_id="message-1",
            scope={"bot": "bot-1", "group": "group-1", "user": "user-1"},
            hash_key=b"test-key",
        )
    )

    files = list(tmp_path.glob("turn_events-*.jsonl"))
    assert len(files) == 1
    row = json.loads(files[0].read_text(encoding="utf-8"))
    assert row["turn_id"] == "turn-1"
    assert row["shape"]["text_len"] == 4
    assert row["message_id_hash"]
    assert "今天好闲" not in files[0].read_text(encoding="utf-8")
    assert "message-1" not in files[0].read_text(encoding="utf-8")


def test_writer_failure_is_contained(tmp_path, monkeypatch) -> None:
    writer = TurnTelemetryWriter(tmp_path, instance_id="test")
    monkeypatch.setattr(writer, "_event_path", lambda: tmp_path / "missing" / "events.jsonl")
    writer.emit({"schema_version": 1, "turn_id": "turn-1", "stage": "ingress"})


def test_report_joins_out_of_order_events_and_counts_provider_retries(tmp_path, monkeypatch) -> None:
    day_key = "2026-08-26"
    monkeypatch.setattr(turn_telemetry, "_day_key", lambda: day_key)
    first = TurnTelemetryWriter(tmp_path, instance_id="first")
    second = TurnTelemetryWriter(tmp_path, instance_id="second")

    second.emit(
        build_turn_event(
            turn_id="turn-1",
            stage="delivery",
            decision="partial",
            delivery_status="partial",
            sent_bubble_count=1,
            total_bubble_count=2,
            hash_key=b"test-key",
        )
    )
    first.emit(
        build_turn_event(
            turn_id="turn-1",
            stage="provider",
            decision="success",
            provider="openai",
            model="model-a",
            attempt=2,
            latency_ms=20,
            prompt_tokens=10,
            completion_tokens=4,
            cost=0.02,
            hash_key=b"test-key",
        )
    )
    second.emit(
        build_turn_event(
            turn_id="turn-1",
            stage="output",
            decision="success",
            output_filter_action="accepted",
            hash_key=b"test-key",
        )
    )
    first.emit(
        build_turn_event(
            turn_id="turn-1",
            stage="provider",
            decision="failed",
            provider="openai",
            model="model-a",
            attempt=1,
            failure_class="timeout",
            latency_ms=5,
            hash_key=b"test-key",
        )
    )
    second.emit(
        build_turn_event(
            turn_id="turn-1",
            stage="ingress",
            decision="proceed",
            text="今天好闲",
            hash_key=b"test-key",
        )
    )

    report = first.report(day_key)

    assert report["funnel"]["turns"] == 1
    assert report["funnel"]["completed"] == 1
    assert report["provider"]["attempts"] == 2
    assert report["provider"]["turns_called"] == 1
    assert report["provider"]["success"] == 1
    assert report["provider"]["failed"] == 1
    assert report["provider"]["tokens"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
    }
    assert report["delivery"]["partial"] == 1
    report_text = json.dumps(report, ensure_ascii=False)
    assert "text_hash" not in report_text
    assert "今天好闲" not in report_text
    assert "turn-1" not in report_text


def test_report_counts_incomplete_turns_and_ignores_bad_lines(tmp_path, monkeypatch) -> None:
    day_key = "2026-08-26"
    monkeypatch.setattr(turn_telemetry, "_day_key", lambda: day_key)
    writer = TurnTelemetryWriter(tmp_path, instance_id="test")
    writer.emit(
        build_turn_event(
            turn_id="turn-incomplete",
            stage="ingress",
            decision="proceed",
            text="你好",
            hash_key=b"test-key",
        )
    )
    event_file = next(tmp_path.glob(f"turn_events-{day_key}-*.jsonl"))
    event_file.write_text(event_file.read_text(encoding="utf-8") + "not-json\n", encoding="utf-8")

    report = writer.report(day_key)

    assert report["funnel"]["turns"] == 1
    assert report["funnel"]["completed"] == 0
    assert report["incomplete_turns"] == 1
    assert report["missing_stages"] == {"delivery": 1, "output": 1}


def test_offline_latency_report_keeps_missing_fields_unknown() -> None:
    from tools.report_llm_latency import summarize_latency_events

    report = summarize_latency_events(
        [
            {"stage": "submit", "context_assembly_ms": 12},
            {"stage": "provider", "latency_ms": 10},
            {"stage": "provider", "latency_ms": 20},
            {
                "stage": "delivery",
                "decision": "partial",
                "delivery_status": "partial",
                "first_reply_latency_ms": 40,
                "delivery_latency_ms": 8,
            },
            {"stage": "delivery", "decision": "silent", "delivery_status": "silent"},
            {"stage": "delivery", "decision": "failed", "delivery_status": "failed", "delivery_latency_ms": 15},
            {"stage": "delivery", "decision": "sent", "delivery_status": "sent", "text": "private"},
        ],
        day_key="2026-10-02",
        source_file_count=2,
    )

    assert report["window"] == {"local_day": "2026-10-02", "source_files": 2}
    assert report["metrics"]["context_assembly_ms"]["sample_count"] == 1
    assert report["metrics"]["provider_request_ms"]["p50_ms"] == 10
    assert report["metrics"]["provider_request_ms"]["p95_ms"] == 20
    assert report["metrics"]["first_effective_reply_ms"]["sample_count"] == 1
    assert report["metrics"]["first_effective_reply_ms"]["unknown_count"] == 3
    assert report["metrics"]["delivery_ms"]["p50_ms"] == 8
    assert report["metrics"]["send_queue_wait_ms"]["status"] == "unknown"
    assert report["delivery_metrics_by_status"]["partial"]["first_effective_reply_ms"]["sample_count"] == 1
    assert report["delivery_metrics_by_status"]["silent"]["first_effective_reply_ms"]["unknown_count"] == 1
    assert report["delivery_metrics_by_status"]["failed"]["delivery_ms"]["p50_ms"] == 15
    assert report["delivery_metrics_by_status"]["sent"]["delivery_ms"]["unknown_count"] == 1
    serialized = json.dumps(report, ensure_ascii=False)
    assert "private" not in serialized
    assert "first_effective_reply_ms" in serialized


def test_latency_report_cli_skips_bad_jsonl_and_never_emits_body(tmp_path, monkeypatch, capsys) -> None:
    from tools.report_llm_latency import main

    day = "2026-10-02"
    event_file = tmp_path / f"turn_events-{day}-test.jsonl"
    event_file.write_text(
        '{"stage":"delivery","delivery_status":"sent","first_reply_latency_ms":17,"text":"private body"}\n{bad json\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["report_llm_latency", "--root", str(tmp_path), "--day", day])

    main()

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["metrics"]["first_effective_reply_ms"]["p50_ms"] == 17
    assert report["metrics"]["first_effective_reply_ms"]["unknown_count"] == 0
    assert "private body" not in output
