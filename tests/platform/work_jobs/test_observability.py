from __future__ import annotations


def test_work_aux_status_round_trip_includes_heartbeat_age(monkeypatch, tmp_path) -> None:
    from pallas.core.platform.work_jobs import observability

    monkeypatch.setattr(observability, "WORK_AUX_STATUS_PATH", tmp_path / "work-status.json")
    monkeypatch.setattr(observability.time, "time", lambda: 100.0)
    observability.write_work_aux_status(
        consumers=4,
        stats={"pending": 3, "leased": 2, "oldest_pending_age_sec": 11.5, "max_attempts": 5},
    )

    monkeypatch.setattr(observability.time, "time", lambda: 107.0)
    assert observability.work_aux_status() == {
        "available": True,
        "heartbeat_age_sec": 7.0,
        "consumers": 4,
        "pending": 3,
        "leased": 2,
        "oldest_pending_age_sec": 11.5,
        "max_attempts": 5,
    }
