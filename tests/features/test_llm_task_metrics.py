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
    record_bot_llm_task("repeater_polish", "submit_ok")
    record_bot_llm_task("repeater_polish", "callback_ok")
    record_bot_llm_task("repeater_fallback", "submit_skip")
    record_bot_llm_task("llm_chat", "callback_fail")
    record_bot_llm_route("llm_chat", "plain_llm_chat")
    record_bot_llm_route("llm_chat", "corpus_select")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["repeater_polish"]["submit_ok"] == 1
    assert snap["by_task"]["repeater_polish"]["callback_ok"] == 1
    assert snap["by_task"]["repeater_fallback"]["submit_skip"] == 1
    assert snap["by_task"]["llm_chat"]["callback_fail"] == 1
    assert snap["by_task"]["llm_chat"]["route_counts"] == {
        "plain_llm_chat": 1,
        "corpus_select": 1,
    }
    clear_llm_task_metrics_for_tests()


def test_record_repeater_stage_routes() -> None:
    clear_llm_task_metrics_for_tests()
    record_bot_llm_route("repeater_select", "pipeline_select")
    record_bot_llm_route("repeater_polish", "pipeline_stitch")
    record_bot_llm_route("repeater_fallback", "pipeline_generate")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["repeater_select"]["route_counts"] == {"pipeline_select": 1}
    assert snap["by_task"]["repeater_polish"]["route_counts"] == {"pipeline_stitch": 1}
    assert snap["by_task"]["repeater_fallback"]["route_counts"] == {"pipeline_generate": 1}
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
