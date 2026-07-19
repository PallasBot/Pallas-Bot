from __future__ import annotations

from types import SimpleNamespace

import packages.pb_webui.extended_api as ext
from packages.pb_webui import daily_stats_store


def test_collect_flush_entries_merges_cluster_and_local(monkeypatch) -> None:
    ext._MSG_STATS.clear()
    ext._PLUGIN_RUN_STATS.clear()
    ext._CONSOLE_CAL_DAY.clear()

    monkeypatch.setattr(ext, "_shard_hub_console", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.load_cluster_console_stats_by_sid",
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
    by_sid = {sid: (day, dr, ds, mr) for day, sid, dr, ds, mr, _api in entries}

    assert by_sid["111"] == ("2026-05-24", 40, 2, 5)
    assert by_sid["222"] == ("2026-05-23", 100, 1, 9)
    assert by_sid["333"] == ("2026-05-24", 7, 1, 3)


def test_console_daily_stats_disk_disabled_on_worker(monkeypatch) -> None:
    monkeypatch.setattr(ext, "_shard_worker_console", lambda: True)
    assert ext._console_daily_stats_disk_enabled() is False

    monkeypatch.setattr(ext, "_shard_worker_console", lambda: False)
    assert ext._console_daily_stats_disk_enabled() is True


def test_daily_stats_store_skips_rewrite_when_batch_is_unchanged(tmp_path, monkeypatch) -> None:
    stats = tmp_path / "console_daily_stats.json"
    monkeypatch.setattr(daily_stats_store, "stats_file_path", lambda: stats)

    daily_stats_store.write_batch_day_totals([("2026-05-24", "111", 40, 2, 5)])
    first = stats.read_text(encoding="utf-8")

    daily_stats_store.write_batch_day_totals([("2026-05-24", "111", 40, 2, 5)])
    second = stats.read_text(encoding="utf-8")

    assert first == second


def test_flush_worker_shard_console_stats_skips_non_local_stale_bots(monkeypatch) -> None:
    ext._MSG_STATS.clear()
    ext._PLUGIN_RUN_STATS.clear()
    ext._CONSOLE_CAL_DAY.clear()

    ext._PLUGIN_RUN_STATS["111"] = {"day_key": "2026-07-04", "by_plugin": {"repeater": {"day_runs": 99}}}
    ext._PLUGIN_RUN_STATS["222"] = {"day_key": "2026-07-04", "by_plugin": {"repeater": {"day_runs": 3}}}
    ext._MSG_STATS["111"] = {"day_key": "2026-07-04", "day_sent": 0, "day_received": 0}
    ext._MSG_STATS["222"] = {"day_key": "2026-07-04", "day_sent": 1, "day_received": 2}

    captured: dict[str, object] = {}

    monkeypatch.setattr(ext, "_shard_worker_console", lambda: True)
    monkeypatch.setattr("nonebot.get_bots", lambda: {"222": object()})
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.get_shard_registry_settings",
        lambda: SimpleNamespace(shard_id=1),
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.filter_local_qq_ids_for_presence",
        lambda local_qq_ids: local_qq_ids,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.reconcile_local_worker_presence_sync",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.write_worker_stats_sync",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.process_memory_snapshot",
        dict,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.ingress_metrics.ingress_metrics_snapshot",
        dict,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.dispatch_metrics.dispatch_metrics_snapshot",
        dict,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.repeater_ingress_metrics.repeater_ingress_metrics_snapshot",
        dict,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.coord_pending.coord_pending_snapshot_sync",
        dict,
    )
    monkeypatch.setattr(
        "pallas.product.llm.task_metrics.llm_task_metrics_snapshot",
        dict,
    )

    ext.flush_worker_shard_console_stats_sync()

    assert captured["shard_id"] == 1
    assert captured["bots"] == {
        "222": {
            "day_key": "2026-07-04",
            "by_plugin": {"repeater": {"day_runs": 3}},
            "matcher_duration_log": [],
            "msg": {
                "day_api_counts": {},
                "day_api_total": 0,
                "day_key": "2026-07-04",
                "day_received": 2,
                "day_sent": 1,
                "received": 0,
                "sent": 0,
                "api_call_buckets": [],
                "msg_traffic_buckets": [],
            },
        }
    }
