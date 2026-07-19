from __future__ import annotations

from pallas.core.platform.shard.ingress_metrics import (
    ingress_metrics_snapshot,
    merge_ingress_metrics,
    record_ingress_claim,
    record_ingress_early_discard,
    record_ingress_event,
    record_ingress_fanout_bypass,
    should_record_ingress_metrics,
)


def test_ingress_metrics_snapshot_and_merge():
    record_ingress_event()
    record_ingress_event()
    record_ingress_early_discard("fleet")
    record_ingress_fanout_bypass()
    record_ingress_claim(won=True)
    record_ingress_claim(won=False)

    snap = ingress_metrics_snapshot()
    assert snap["events"] == 2
    assert snap["early_fleet"] == 1
    assert snap["fanout_bypass"] == 1
    assert snap["claim_won"] == 1
    assert snap["claim_lost"] == 1
    assert snap["claim_hit_rate"] == 0.5

    cluster = merge_ingress_metrics([snap, {"day_key": snap["day_key"], "claim_won": 1, "claim_lost": 0}])
    assert cluster["claim_won"] == 2
    assert cluster["claim_lost"] == 1
    assert round(cluster["claim_hit_rate"], 4) == round(2 / 3, 4)


def test_should_record_ingress_metrics_unified(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: False,
    )
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({10002, 10001}),
    )
    assert should_record_ingress_metrics(10001) is True
    assert should_record_ingress_metrics(10002) is False


def test_should_record_ingress_metrics_unified_empty_fleet(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: False,
    )
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset(),
    )
    assert should_record_ingress_metrics(12345) is True


def test_should_record_ingress_metrics_shard_rep(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.local_representative.is_local_worker_representative",
        lambda bot_id: bot_id == 10001,
    )
    assert should_record_ingress_metrics(10001) is True
    assert should_record_ingress_metrics(10002) is False
