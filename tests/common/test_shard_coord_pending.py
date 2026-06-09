from __future__ import annotations

from src.platform.shard.coord_pending import coord_pending_snapshot_sync


def test_coord_pending_redis_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.platform.shard.coord_pending.coord_redis_enabled",
        lambda: False,
    )
    snap = coord_pending_snapshot_sync()
    assert snap["storage"] == "redis"
    assert snap["total_json"] == 0
    assert snap["actionable_total"] == 0
    assert snap["bot_action_open"] == 0
    assert snap["bot_action_stale_open"] == 0
    assert snap["scan_skipped"] is False


def test_coord_pending_redis_snapshot_skips_live_scan_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.platform.shard.coord_pending.coord_redis_enabled",
        lambda: True,
    )

    def fail_scan(_prefix: str) -> list[str]:
        raise AssertionError("scan_keys_sync should not run on default fast path")

    monkeypatch.setattr(
        "src.platform.shard.coord_pending.scan_keys_sync",
        fail_scan,
    )

    snap = coord_pending_snapshot_sync()

    assert snap["storage"] == "redis"
    assert snap["total_json"] == 0
    assert snap["actionable_total"] == 0
    assert snap["historical_retained"] == 0
    assert snap["scan_skipped"] is True


def test_coord_pending_redis_snapshot_counts_known_namespaces(monkeypatch) -> None:
    keys_by_prefix = {
        "pallas:coord:bot_action:": [
            "pallas:coord:bot_action:req_open",
            "pallas:coord:bot_action:req_done",
        ],
        "pallas:coord:bot_count:": ["pallas:coord:bot_count:1:2"],
        "pallas:coord:cage_duel:": ["pallas:coord:cage_duel:1:3"],
        "pallas:coord:duel_group:": ["pallas:coord:duel_group:1"],
        "pallas:coord:group_gate:": ["pallas:coord:group_gate:broadcast:test:1"],
        "pallas:coord:maa_pending:": [
            "pallas:coord:maa_pending:queue:user_dev",
            "pallas:coord:maa_pending:idx:task1",
        ],
        "pallas:coord:maa_route:": ["pallas:coord:maa_route:123456"],
        "pallas:coord:maa_seen:": ["pallas:coord:maa_seen:123456:dev"],
        "pallas:coord:repeater_buffer:": [],
        "pallas:coord:repeater_reply_buffer:": ["pallas:coord:repeater_reply_buffer:e1"],
        "pallas:duel_qte:session:": ["pallas:duel_qte:session:s_1_2"],
        "pallas:duel_qte:greeting_users:": ["pallas:duel_qte:greeting_users:1"],
        "pallas:ai_task:": ["pallas:ai_task:task_1"],
    }
    payloads = {
        "pallas:coord:bot_action:req_open": {"done": False},
        "pallas:coord:bot_action:req_done": {"done": True},
    }

    monkeypatch.setattr(
        "src.platform.shard.coord_pending.coord_redis_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.platform.shard.coord_pending.scan_keys_sync",
        lambda prefix: list(keys_by_prefix.get(prefix, [])),
    )
    monkeypatch.setattr(
        "src.platform.shard.coord_pending.read_json_sync",
        lambda key: payloads.get(key),
    )

    snap = coord_pending_snapshot_sync(live=True)

    assert snap["storage"] == "redis"
    assert snap["total_json"] == 14
    assert snap["actionable_total"] == 1
    assert snap["historical_retained"] == 1
    assert snap["scan_skipped"] is False
    assert snap["bot_action_open"] == 1
    assert snap["bot_action_stale_open"] == 0
    assert snap["by_dir"]["bot_action"] == 2
    assert snap["by_dir"]["bot_count"] == 1
    assert snap["by_dir"]["cage_duel"] == 1
    assert snap["by_dir"]["duel_group"] == 1
    assert snap["by_dir"]["group_gate"] == 1
    assert snap["by_dir"]["maa_pending"] == 2
    assert snap["by_dir"]["maa_route"] == 1
    assert snap["by_dir"]["maa_seen"] == 1
    assert snap["by_dir"]["repeater_buffer"] == 0
    assert snap["by_dir"]["repeater_reply_buffer"] == 1
    assert snap["by_dir"]["duel_qte_session"] == 1
    assert snap["by_dir"]["duel_qte_greeting"] == 1
    assert snap["by_dir"]["ai_task"] == 1
