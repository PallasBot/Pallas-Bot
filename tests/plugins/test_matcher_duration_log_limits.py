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
