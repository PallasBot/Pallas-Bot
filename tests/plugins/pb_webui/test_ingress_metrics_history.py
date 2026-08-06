from __future__ import annotations


def test_ingress_history_aggregates_counter_deltas_and_peak_gauges(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: tmp_path / "ingress_metrics_history.jsonl")
    first = {
        "group_messages": 100,
        "ingress_duration_ms_p95": 300.0,
        "conversation_scheduler": {"pending": 2, "active": 1, "concurrency": 8, "wait_ms_p95": 120.0},
        "work_aux": {"pending": 1, "leased": 1, "completed_since_start": 20},
        "hotpath": {"learn_enqueued": 30, "learn_persisted": 29},
    }
    second = {
        "group_messages": 112,
        "ingress_duration_ms_p95": 1_400.0,
        "conversation_scheduler": {"pending": 7, "active": 4, "concurrency": 8, "wait_ms_p95": 900.0},
        "work_aux": {"pending": 3, "leased": 2, "completed_since_start": 27},
        "hotpath": {"learn_enqueued": 39, "learn_persisted": 38},
    }
    third = {
        "group_messages": 118,
        "ingress_duration_ms_p95": 600.0,
        "conversation_scheduler": {"pending": 1, "active": 2, "concurrency": 8, "wait_ms_p95": 240.0},
        "work_aux": {"pending": 0, "leased": 1, "completed_since_start": 31},
        "hotpath": {"learn_enqueued": 44, "learn_persisted": 44},
    }

    assert mod.append_ingress_metrics_history(snapshot=first, ts=100)
    assert mod.append_ingress_metrics_history(snapshot=second, ts=115)
    assert mod.append_ingress_metrics_history(snapshot=third, ts=130)

    data = mod.read_ingress_metrics_history(window_sec=30, bucket_sec=30, now=130)

    assert data["bucket_sec"] == 30
    assert data["points"] == [
        {
            "at": 90,
            "ingress_p95_ms": 1_400.0,
            "scheduler_wait_p95_ms": 900.0,
            "scheduler_pending": 7,
            "scheduler_active": 4,
            "scheduler_capacity": 8,
            "work_pending": 3,
            "work_leased": 2,
            "group_messages": 12,
            "learn_enqueued": 9,
            "learn_persisted": 9,
            "work_completed": 7,
        },
        {
            "at": 120,
            "ingress_p95_ms": 600.0,
            "scheduler_wait_p95_ms": 240.0,
            "scheduler_pending": 1,
            "scheduler_active": 2,
            "scheduler_capacity": 8,
            "work_pending": 0,
            "work_leased": 1,
            "group_messages": 6,
            "learn_enqueued": 5,
            "learn_persisted": 6,
            "work_completed": 4,
        },
    ]


def test_ingress_history_discards_expired_rows(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: tmp_path / "ingress_metrics_history.jsonl")
    assert mod.append_ingress_metrics_history(snapshot={}, ts=10)
    assert mod.append_ingress_metrics_history(snapshot={}, ts=20)

    assert mod.prune_ingress_metrics_history(now=20 + mod.INGRESS_HISTORY_RETENTION_SEC)
    assert mod.read_ingress_metrics_history(window_sec=60, bucket_sec=15, now=20 + mod.INGRESS_HISTORY_RETENTION_SEC)["points"] == []
