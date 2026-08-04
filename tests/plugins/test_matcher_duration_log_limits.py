from packages.pb_webui import console_metrics_runtime
from packages.pb_webui.extended_api import (
    _MATCHER_DURATION_LOG_CAP,
    _MATCHER_DURATION_LOG_PER_PLUGIN_CAP,
    enforce_matcher_duration_log_limits,
)


def test_enforce_matcher_duration_log_limits_per_plugin_and_total():
    log = [{"at": i, "plugin": "repeater", "duration_ms": 0.0} for i in range(90)]
    log.extend({"at": 100 + i, "plugin": "other", "duration_ms": 1.0} for i in range(15))
    enforce_matcher_duration_log_limits(log)
    assert len(log) <= _MATCHER_DURATION_LOG_CAP
    by_plugin: dict[str, int] = {}
    for it in log:
        by_plugin[it["plugin"]] = by_plugin.get(it["plugin"], 0) + 1
    assert by_plugin["repeater"] <= _MATCHER_DURATION_LOG_PER_PLUGIN_CAP
    assert by_plugin["other"] == 15


def test_matcher_duration_log_flushes_with_unified_stats_cycle(monkeypatch):
    monkeypatch.setattr(console_metrics_runtime, "_PLUGIN_RUN_STATS", {})
    monkeypatch.setattr(console_metrics_runtime, "_MATCHER_DURATION_LOG_DIRTY", False, raising=False)
    monkeypatch.setattr(console_metrics_runtime, "shard_worker_console", lambda: False)
    monkeypatch.setattr(console_metrics_runtime, "shard_hub_console", lambda: False)
    monkeypatch.setattr(console_metrics_runtime, "_unified_console_live_stats_enabled", lambda: True)
    rewrites: list[None] = []
    monkeypatch.setattr(
        console_metrics_runtime,
        "_rewrite_matcher_durations_jsonl",
        lambda: rewrites.append(None),
    )
    from packages.pb_webui import console_live_stats

    monkeypatch.setattr(console_live_stats, "write_bots_sync", lambda *_args, **_kwargs: None)

    console_metrics_runtime._append_matcher_duration_log(
        "10001",
        "repeater",
        12.0,
        had_error=False,
    )

    assert rewrites == []
    console_metrics_runtime.flush_unified_console_live_stats_sync()
    assert rewrites == [None]
    console_metrics_runtime.flush_unified_console_live_stats_sync()
    assert rewrites == [None]
