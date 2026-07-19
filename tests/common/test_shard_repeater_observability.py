from __future__ import annotations

from pallas.core.platform.shard import console_stats as stats_mod
from pallas.core.platform.shard.observability import aggregate_shard_observability


def test_aggregate_shard_observability_includes_repeater_ingress(tmp_path, monkeypatch):
    monkeypatch.setattr(stats_mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.observability.get_shard_registry",
        lambda: type("R", (), {"shards": [type("S", (), {"id": 0})()]})(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.bot_authoritative_shard_map",
        dict,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.observability.coord_pending_snapshot_sync",
        dict,
    )

    stats_mod.write_worker_stats_sync(
        shard_id=0,
        bots={},
        worker_meta={
            "ingress": {"day_key": "2026-06-05", "events": 1},
            "repeater_ingress": {
                "day_key": "2026-06-05",
                "events": 3,
                "claim_won": 2,
                "claim_lost": 1,
            },
            "coord_pending": {},
            "process_memory": {"rss": 12_345_678, "vms": 23_456_789},
        },
    )

    data = aggregate_shard_observability()
    assert data["repeater_ingress_cluster"]["events"] == 3
    assert data["repeater_ingress_cluster"]["claim_won"] == 2
    assert data["workers"][0]["repeater_ingress"]["claim_lost"] == 1
    assert data["workers"][0]["process_memory"] == {"rss": 12_345_678, "vms": 23_456_789}
