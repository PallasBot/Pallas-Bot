from pallas.product.llm.task_metrics import (
    clear_llm_task_metrics_for_tests,
    cluster_llm_task_metrics_snapshot,
    llm_task_metrics_snapshot,
    merge_llm_task_snapshots,
    record_bot_llm_route,
    record_bot_llm_task,
)


def test_record_bot_llm_task_snapshot() -> None:
    clear_llm_task_metrics_for_tests()
    record_bot_llm_task("llm_chat", "submit_ok")
    record_bot_llm_task("llm_chat", "callback_fail")
    record_bot_llm_route("llm_chat", "plain_llm_chat")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["submit_ok"] == 1
    assert snap["by_task"]["llm_chat"]["callback_fail"] == 1
    assert snap["by_task"]["llm_chat"]["route_counts"] == {"plain_llm_chat": 1}
    clear_llm_task_metrics_for_tests()


def test_record_bot_llm_task_background_events() -> None:
    clear_llm_task_metrics_for_tests()
    record_bot_llm_task("llm_chat", "background_enqueued")
    record_bot_llm_task("llm_chat", "background_coalesced")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["background_enqueued"] == 1
    assert snap["by_task"]["llm_chat"]["background_coalesced"] == 1
    assert snap["totals"]["background_enqueued"] == 1
    assert snap["totals"]["background_coalesced"] == 1
    clear_llm_task_metrics_for_tests()


def test_track_llm_callback_ignores_retired_repeater_task() -> None:
    from pallas.product.llm.delivery import track_llm_callback

    clear_llm_task_metrics_for_tests()
    track_llm_callback(
        {"task_type": "repeater_fallback", "llm_route": "pipeline_generate"},
        "callback_ok",
    )
    track_llm_callback({"task_type": "repeater_fallback"}, "callback_ok")
    snap = llm_task_metrics_snapshot()
    assert "repeater_fallback" not in snap["by_task"]
    clear_llm_task_metrics_for_tests()


def test_track_llm_callback_records_explicit_llm_chat_route() -> None:
    from pallas.product.llm.delivery import track_llm_callback

    clear_llm_task_metrics_for_tests()
    track_llm_callback(
        {"task_type": "llm_chat", "llm_route": "plain_llm_chat"},
        "callback_ok",
    )
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["callback_ok"] == 1
    assert snap["by_task"]["llm_chat"]["route_counts"] == {"plain_llm_chat": 1}
    clear_llm_task_metrics_for_tests()


def test_track_llm_callback_splits_reply_route_by_trigger() -> None:
    from pallas.product.llm.delivery import track_llm_callback

    clear_llm_task_metrics_for_tests()
    track_llm_callback({"task_type": "llm_chat", "speak_trigger": "to_me"}, "callback_ok")
    track_llm_callback({"task_type": "llm_chat", "speak_trigger": "alias"}, "callback_ok")
    track_llm_callback({"task_type": "llm_chat", "speak_trigger": "mention"}, "callback_ok")
    track_llm_callback({"task_type": "llm_chat", "speak_trigger": "ambient"}, "callback_ok")
    track_llm_callback({"task_type": "llm_chat", "speak_trigger": "followup"}, "callback_ok")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["route_counts"] == {
        "plain_llm_chat": 1,
        "alias": 2,
        "ambient": 1,
        "followup": 1,
    }
    clear_llm_task_metrics_for_tests()


def test_merge_llm_task_snapshots() -> None:
    merged = merge_llm_task_snapshots([
        {
            "day_key": "2026-06-17",
            "updated_at": 100.0,
            "by_task": {
                "llm_chat": {
                    "submit_ok": 2,
                    "submit_skip": 0,
                    "callback_ok": 1,
                    "callback_fail": 0,
                    "reply_gate_skip": 0,
                    "reply_gate_defer": 0,
                    "route_counts": {
                        "plain_llm_chat": 2,
                    },
                }
            },
            "totals": {
                "submit_ok": 2,
                "submit_skip": 0,
                "callback_ok": 1,
                "callback_fail": 0,
                "reply_gate_skip": 0,
                "reply_gate_defer": 0,
            },
        },
        {
            "day_key": "2026-06-17",
            "updated_at": 200.0,
            "by_task": {
                "repeater_polish": {
                    "submit_ok": 1,
                    "submit_skip": 0,
                    "callback_ok": 1,
                    "callback_fail": 0,
                    "reply_gate_skip": 0,
                    "reply_gate_defer": 0,
                    "route_counts": {
                        "corpus_polish": 1,
                    },
                }
            },
            "totals": {
                "submit_ok": 1,
                "submit_skip": 0,
                "callback_ok": 1,
                "callback_fail": 0,
                "reply_gate_skip": 0,
                "reply_gate_defer": 0,
            },
        },
    ])
    assert merged["source"] == "bot_cluster"
    assert merged["by_task"]["llm_chat"]["submit_ok"] == 2
    assert merged["by_task"]["repeater_polish"]["submit_ok"] == 1
    assert merged["by_task"]["llm_chat"]["route_counts"] == {"plain_llm_chat": 2}
    assert merged["by_task"]["repeater_polish"]["route_counts"] == {"corpus_polish": 1}
    assert merged["totals"]["submit_ok"] == 3
    assert merged["updated_at"] == 200.0


def test_cluster_llm_task_metrics_snapshot_from_workers(tmp_path, monkeypatch) -> None:
    clear_llm_task_metrics_for_tests()
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_hub", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.plugin_data_dir", lambda name, create=True: tmp_path / name
    )
    from pallas.core.platform.shard import console_stats as stats_mod

    stats_mod.write_worker_stats_sync(
        shard_id=0,
        bots={},
        worker_meta={
            "llm_task": {
                "day_key": "2026-06-17",
                "updated_at": 999.0,
                "by_task": {
                    "llm_chat": {
                        "submit_ok": 4,
                        "submit_skip": 0,
                        "callback_ok": 0,
                        "callback_fail": 0,
                        "reply_gate_skip": 0,
                        "reply_gate_defer": 0,
                    }
                },
                "totals": {
                    "submit_ok": 4,
                    "submit_skip": 0,
                    "callback_ok": 0,
                    "callback_fail": 0,
                    "reply_gate_skip": 0,
                    "reply_gate_defer": 0,
                },
            }
        },
    )
    record_bot_llm_task("llm_chat", "submit_ok")
    snap = cluster_llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["submit_ok"] == 5
    clear_llm_task_metrics_for_tests()


def test_record_bot_llm_task_guardrail_events() -> None:
    clear_llm_task_metrics_for_tests()
    record_bot_llm_task("llm_chat", "persona_firewall_hit")
    record_bot_llm_task("llm_chat", "persona_firewall_retry")
    record_bot_llm_task("llm_chat", "output_filter_block")
    record_bot_llm_task("llm_chat", "reply_silenced")
    snap = llm_task_metrics_snapshot()
    chat_stats = snap["by_task"]["llm_chat"]
    assert chat_stats["persona_firewall_hit"] == 1
    assert chat_stats["persona_firewall_retry"] == 1
    assert chat_stats["output_filter_block"] == 1
    assert chat_stats["reply_silenced"] == 1
    assert snap["totals"]["output_filter_block"] == 1
    clear_llm_task_metrics_for_tests()
