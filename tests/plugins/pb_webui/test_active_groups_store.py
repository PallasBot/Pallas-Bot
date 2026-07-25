from __future__ import annotations

from packages.pb_webui import active_groups_store


def test_write_and_compute_dag_mag(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(active_groups_store, "stats_file_path", lambda: tmp_path / "console_active_groups.json")
    active_groups_store.write_day_groups("2026-07-01", "111", ["10", "20"])
    active_groups_store.write_day_groups("2026-07-02", "111", ["20", "30"])
    active_groups_store.write_day_groups(
        "2026-07-25",
        "111",
        ["30", "40"],
    )
    metrics = active_groups_store.compute_group_metrics(
        self_id="111",
        today="2026-07-25",
        mag_days=30,
        live_today={"111": {"40", "50"}},
    )
    assert metrics["dag"] == 3  # 30,40,50
    assert metrics["mag"] == 5  # 10,20,30,40,50
    assert metrics["dag_mag_ratio"] == round(3 / 5, 4)

    rows = active_groups_store.load_daily_active_counts(
        self_id="111",
        start_day="2026-07-01",
        end_day="2026-07-02",
    )
    assert [r["active_groups"] for r in rows] == [2, 2]


def test_merge_day_groups_unions() -> None:
    assert active_groups_store.merge_day_groups(["1", "2"], [2, 3]) == ["1", "2", "3"]
