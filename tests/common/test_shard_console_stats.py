from __future__ import annotations

from pallas.core.platform.shard import console_stats as mod


def test_worker_stats_roundtrip_and_cluster_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "bot_authoritative_shard_map", lambda: {"111": 0, "222": 1})

    bots0 = {
        "111": {
            "day_key": "2026-05-22",
            "by_plugin": {"duel": {"runs": 3, "day_runs": 2, "errors": 0, "day_errors": 0}},
            "matcher_duration_log": [{"at": 1, "plugin": "duel", "duration_ms": 12.5, "had_error": False}],
            "msg": {"sent": 1, "received": 2, "day_sent": 1, "day_received": 2, "day_key": "2026-05-22"},
        }
    }
    bots1 = {
        "222": {
            "day_key": "2026-05-22",
            "by_plugin": {"help": {"runs": 1, "day_runs": 1, "errors": 0, "day_errors": 0}},
            "matcher_duration_log": [],
            "msg": {"sent": 0, "received": 1, "day_sent": 0, "day_received": 1, "day_key": "2026-05-22"},
        }
    }
    mod.write_worker_stats_sync(shard_id=0, bots=bots0)
    mod.write_worker_stats_sync(shard_id=1, bots=bots1)

    merged = mod.load_cluster_console_stats_by_sid()
    assert set(merged.keys()) == {"111", "222"}
    assert merged["111"]["by_plugin"]["duel"]["day_runs"] == 2
    assert len(merged["111"]["matcher_duration_log"]) == 1


def test_cluster_merge_prefers_authoritative_shard_over_stale_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "bot_authoritative_shard_map", lambda: {"111": 0})

    stale = {
        "111": {
            "day_key": "2026-05-25",
            "by_plugin": {"duel": {"runs": 99, "day_runs": 99, "errors": 0, "day_errors": 0}},
            "matcher_duration_log": [{"at": 100, "plugin": "duel", "duration_ms": 1.0, "had_error": False}],
            "msg": {},
        }
    }
    fresh = {
        "111": {
            "day_key": "2026-05-26",
            "by_plugin": {"duel": {"runs": 3, "day_runs": 3, "errors": 0, "day_errors": 0}},
            "matcher_duration_log": [{"at": 200, "plugin": "duel", "duration_ms": 2.0, "had_error": False}],
            "msg": {},
        }
    }
    mod.write_worker_stats_sync(shard_id=99, bots=stale)
    mod.write_worker_stats_sync(shard_id=0, bots=fresh)

    merged = mod.load_cluster_console_stats_by_sid()
    assert merged["111"]["by_plugin"]["duel"]["day_runs"] == 3
    assert merged["111"]["matcher_duration_log"][0]["duration_ms"] == 2.0


def test_prune_stale_worker_stats_bots_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)

    class FakeReg:
        def bots_on_shard(self, shard_id: int) -> list[str]:
            if int(shard_id) == 99:
                return []
            if int(shard_id) == 0:
                return ["111"]
            return []

    monkeypatch.setattr("pallas.core.platform.shard.registry.store.get_shard_registry", lambda: FakeReg())

    mod.write_worker_stats_sync(
        shard_id=99,
        bots={
            "111": {
                "day_key": "2026-05-25",
                "by_plugin": {},
                "matcher_duration_log": [],
                "msg": {},
            }
        },
    )
    removed = mod.prune_stale_worker_stats_bots_sync()
    assert removed == 1
    assert mod.read_worker_stats(99) == {}


def test_load_worker_console_stats_for_boot_filters_bots_moved_to_other_shards(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "bot_authoritative_shard_map", lambda: {"111": 0, "222": 1})

    mod.write_worker_stats_sync(
        shard_id=1,
        bots={
            "111": {
                "day_key": "2026-07-04",
                "by_plugin": {"repeater": {"day_runs": 99}},
                "matcher_duration_log": [],
                "msg": {},
            },
            "222": {
                "day_key": "2026-07-04",
                "by_plugin": {"repeater": {"day_runs": 3}},
                "matcher_duration_log": [],
                "msg": {},
            },
        },
    )

    boot = mod.load_worker_console_stats_for_boot(1)
    assert boot == {
        "222": {
            "day_key": "2026-07-04",
            "by_plugin": {"repeater": {"day_runs": 3}},
            "matcher_duration_log": [],
            "msg": {},
        }
    }


def test_preserve_matcher_hist_on_fast_flush(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)

    hist = [{"at": 100, "plugins": {"duel": 1}}]
    mod.write_worker_stats_sync(
        shard_id=0,
        bots={
            "111": {
                "day_key": "2026-05-22",
                "by_plugin": {},
                "matcher_hist": hist,
                "matcher_duration_log": [],
                "msg": {},
            }
        },
    )
    mod.write_worker_stats_sync(
        shard_id=0,
        bots={
            "111": {
                "day_key": "2026-05-22",
                "by_plugin": {"duel": {"day_runs": 3}},
                "matcher_duration_log": [],
                "msg": {},
            }
        },
        preserve_matcher_hist=True,
    )
    row = mod.read_worker_stats(0)["111"]
    assert row["matcher_hist"] == hist
    assert row["by_plugin"]["duel"]["day_runs"] == 3


def test_iter_worker_shard_ids_filters_stale(tmp_path, monkeypatch):
    import json
    import time

    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    stats_dir = mod.stats_dir()
    stats_dir.mkdir(parents=True, exist_ok=True)
    mod.write_worker_stats_sync(shard_id=0, bots={})
    stale_path = stats_dir / "worker-99.json"
    stale_path.write_text(
        json.dumps({"v": 1, "shard_id": 99, "updated_at": time.time() - 600, "bots": {}}),
        encoding="utf-8",
    )
    assert mod.iter_worker_shard_ids() == [0, 99]
    assert mod.iter_worker_shard_ids(max_stale_sec=mod.WORKER_STATS_ACTIVE_SEC) == [0]
