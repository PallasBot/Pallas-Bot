from __future__ import annotations

import json


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
    history = mod.read_ingress_metrics_history(
        window_sec=60,
        bucket_sec=15,
        now=20 + mod.INGRESS_HISTORY_RETENTION_SEC,
    )
    assert history["points"] == []


def test_route_candidates_are_sanitized_and_only_written_when_changed(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    path = tmp_path / "ingress_metrics_history.jsonl"
    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: path)
    candidate = {
        "route_modules": ["drink"],
        "messages": 3,
        "route_index_hits": 3,
        "matchers_selected": 6,
        "ingress_duration_ms_p95": 12.5,
        "eligible": True,
        "message": "secret",
        "group_id": 733291779,
    }

    assert mod.append_ingress_metrics_history(
        snapshot={"day_key": "2026-08-10", "route_candidates": [candidate]}, ts=100
    )
    assert mod.append_ingress_metrics_history(
        snapshot={"day_key": "2026-08-10", "route_candidates": [candidate]}, ts=115
    )
    changed = dict(candidate, messages=4)
    assert mod.append_ingress_metrics_history(snapshot={"day_key": "2026-08-10", "route_candidates": [changed]}, ts=130)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["route_candidates"][0]["messages"] == 3
    assert "message" not in rows[0]["route_candidates"][0]
    assert "group_id" not in rows[0]["route_candidates"][0]
    assert "route_candidates" not in rows[1]
    assert rows[2]["route_candidates"][0]["messages"] == 4

    history = mod.read_route_candidate_history(now=130)
    assert history["day_key"] == "2026-08-10"
    assert [row["ts"] for row in history["changes"]] == [100, 130]
    assert history["latest"][0]["messages"] == 4


def test_route_candidates_persist_again_when_day_changes(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    path = tmp_path / "ingress_metrics_history.jsonl"
    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: path)
    candidate = {"route_modules": ["drink"], "messages": 1}

    assert mod.append_ingress_metrics_history(
        snapshot={"day_key": "2026-08-10", "route_candidates": [candidate]}, ts=100
    )
    assert mod.append_ingress_metrics_history(
        snapshot={"day_key": "2026-08-11", "route_candidates": [candidate]}, ts=200
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert "route_candidates" in rows[1]


def test_route_candidate_cache_hydrates_and_rebuilds_counter_resets(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    path = tmp_path / "ingress_metrics_history.jsonl"
    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: path)
    rows = [
        {
            "ts": 100,
            "day_key": "2026-08-10",
            "route_candidates": [{"route_modules": ["drink"], "messages": 5, "matchers_selected": 10}],
        },
        {
            "ts": 200,
            "day_key": "2026-08-10",
            "route_candidates": [{"route_modules": ["drink"], "messages": 2, "matchers_selected": 4}],
        },
        {
            "ts": 300,
            "day_key": "2026-08-10",
            "route_candidates": [{"route_modules": ["drink"], "messages": 4, "matchers_selected": 8}],
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    mod.hydrate_route_candidate_history_cache(now=300)
    snapshot = mod.route_candidate_history_snapshot()

    assert snapshot["day_key"] == "2026-08-10"
    assert snapshot["latest_at"] == 300
    assert snapshot["today_totals"][0]["messages"] == 9
    assert snapshot["today_totals"][0]["matchers_selected"] == 18
    assert snapshot["write_ok"] is True


def test_route_candidate_cache_marks_write_failure(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: parent_file / "history.jsonl")

    assert not mod.append_ingress_metrics_history(
        snapshot={"day_key": "2026-08-10", "route_candidates": []},
        ts=100,
    )
    assert mod.route_candidate_history_snapshot()["write_ok"] is False


def test_sharded_route_candidates_do_not_accumulate_aggregate_resets(tmp_path, monkeypatch) -> None:
    from packages.pb_webui import ingress_metrics_history as mod

    monkeypatch.setattr(mod, "ingress_metrics_history_path", lambda: tmp_path / "history.jsonl")
    assert mod.append_ingress_metrics_history(
        snapshot={
            "day_key": "2026-08-10",
            "sharded": True,
            "route_candidates": [{"route_modules": ["drink"], "messages": 100}],
        },
        ts=100,
    )
    assert mod.append_ingress_metrics_history(
        snapshot={
            "day_key": "2026-08-10",
            "sharded": True,
            "route_candidates": [{"route_modules": ["drink"], "messages": 50}],
        },
        ts=115,
    )

    snapshot = mod.route_candidate_history_snapshot()
    assert snapshot["sharded"] is True
    assert snapshot["today_totals"] == []
