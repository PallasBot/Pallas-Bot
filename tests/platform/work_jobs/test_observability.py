from __future__ import annotations

from pallas.core.platform.work_jobs import observability


def test_work_aux_status_round_trip_includes_heartbeat_age(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(observability, "WORK_AUX_STATUS_PATH", tmp_path / "work-status.json")
    monkeypatch.setattr(observability.time, "time", lambda: 100.0)
    observability.write_work_aux_status(
        consumers=4,
        stats={"pending": 3, "leased": 2, "dead_lettered": 1, "oldest_pending_age_sec": 11.5, "max_attempts": 5},
    )

    monkeypatch.setattr(observability.time, "time", lambda: 107.0)
    assert observability.work_aux_status() == {
        "available": True,
        "heartbeat_age_sec": 7.0,
        "consumers": 4,
        "pending": 3,
        "leased": 2,
        "dead_lettered": 1,
        "oldest_pending_age_sec": 11.5,
        "max_attempts": 5,
        "completed_since_start": 0,
        "failed_since_start": 0,
        "retried_since_start": 0,
        "dead_lettered_since_start": 0,
    }


def test_work_aux_status_includes_runtime_counters(tmp_path, monkeypatch) -> None:
    status_path = tmp_path / "status.json"
    monkeypatch.setattr(observability, "WORK_AUX_STATUS_PATH", status_path)

    observability.write_work_aux_status(
        consumers=3,
        stats={"pending": 0, "leased": 0, "dead_lettered": 0, "oldest_pending_age_sec": None, "max_attempts": 1},
        runtime_metrics={
            "completed_since_start": 12,
            "failed_since_start": 3,
            "retried_since_start": 2,
            "dead_lettered_since_start": 1,
        },
    )

    assert observability.work_aux_status()["completed_since_start"] == 12
    assert observability.work_aux_status()["failed_since_start"] == 3
    assert observability.work_aux_status()["retried_since_start"] == 2
    assert observability.work_aux_status()["dead_lettered_since_start"] == 1
