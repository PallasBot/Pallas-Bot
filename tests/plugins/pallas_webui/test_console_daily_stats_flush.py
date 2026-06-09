from __future__ import annotations

import src.plugins.pallas_webui.extended_api as ext
from src.plugins.pallas_webui import daily_stats_store


def test_collect_flush_entries_merges_cluster_and_local(monkeypatch) -> None:
    ext._MSG_STATS.clear()
    ext._PLUGIN_RUN_STATS.clear()
    ext._CONSOLE_CAL_DAY.clear()

    monkeypatch.setattr("src.platform.shard.registry.config.is_sharding_active", lambda: True)
    monkeypatch.setattr("src.platform.bot_runtime.roles.is_sharded_hub", lambda: True)
    monkeypatch.setattr(
        "src.platform.shard.console_stats.load_cluster_console_stats_by_sid",
        lambda: {
            "111": {
                "day_key": "2026-05-24",
                "msg": {"day_key": "2026-05-24", "day_received": 40, "day_sent": 2},
                "by_plugin": {"help": {"day_runs": 5}},
            },
            "222": {
                "day_key": "2026-05-23",
                "msg": {"day_key": "2026-05-23", "day_received": 100, "day_sent": 1},
                "by_plugin": {"duel": {"day_runs": 9}},
            },
        },
    )

    ext._MSG_STATS["333"] = {
        "day_received": 7,
        "day_sent": 1,
        "day_key": "2026-05-24",
    }
    ext._PLUGIN_RUN_STATS["333"] = {
        "day_key": "2026-05-24",
        "by_plugin": {"like": {"day_runs": 3}},
    }
    ext._CONSOLE_CAL_DAY["333"] = "2026-05-24"

    entries = ext._collect_console_daily_flush_entries("2026-05-24")
    by_sid = {sid: (day, dr, ds, mr) for day, sid, dr, ds, mr in entries}

    assert by_sid["111"] == ("2026-05-24", 40, 2, 5)
    assert by_sid["222"] == ("2026-05-23", 100, 1, 9)
    assert by_sid["333"] == ("2026-05-24", 7, 1, 3)


def test_console_daily_stats_disk_disabled_on_worker(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.platform.bot_runtime.roles.is_sharded_worker",
        lambda: True,
    )
    assert ext._console_daily_stats_disk_enabled() is False

    monkeypatch.setattr(
        "src.platform.bot_runtime.roles.is_sharded_worker",
        lambda: False,
    )
    assert ext._console_daily_stats_disk_enabled() is True


def test_daily_stats_store_skips_rewrite_when_batch_is_unchanged(tmp_path, monkeypatch) -> None:
    stats = tmp_path / "console_daily_stats.json"
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: stats)

    daily_stats_store.write_batch_day_totals([("2026-05-24", "111", 40, 2, 5)])
    first = stats.read_text(encoding="utf-8")

    daily_stats_store.write_batch_day_totals([("2026-05-24", "111", 40, 2, 5)])
    second = stats.read_text(encoding="utf-8")

    assert first == second
