from __future__ import annotations

from packages.pb_webui import extended_api as api


def test_plugin_run_stats_overview_skips_log_errors_when_scoped(monkeypatch):
    monkeypatch.setattr(api, "_shard_hub_console", lambda: False)
    monkeypatch.setattr(api, "get_bots", dict)
    monkeypatch.setattr(api, "_log_error_log_public", lambda **_kw: [{"at": 1}])
    monkeypatch.setattr(api, "_log_error_log_meta", lambda: {"sharded_log_errors": False, "log_error_sources": ["hub"]})

    out = api._plugin_run_stats_overview(self_id="12345", include_log_errors=False)
    assert "log_error_log" not in out
    assert out["bots"] == []


def test_log_errors_payload_shape(monkeypatch):
    sample = [{"at": 9, "plugin": "hub", "exc_type": "E", "message": "m", "traceback": ""}]
    monkeypatch.setattr(api, "_log_error_log_public", lambda **_kw: sample)
    monkeypatch.setattr(api, "_log_error_log_meta", lambda: {"sharded_log_errors": False, "log_error_sources": ["hub"]})

    out = api._log_errors_payload(source="all", tb_limit=0, limit=10)
    assert out["log_error_log"] == sample
    assert out["sharded_log_errors"] is False


def test_log_error_public_cache_reused(monkeypatch):
    api._invalidate_log_error_public_cache()
    calls = {"n": 0}

    def fake_collect(**_kw):
        calls["n"] += 1
        return []

    monkeypatch.setattr(api, "_shard_hub_console", lambda: False)
    with api._LOG_ERROR_JSONL_LOCK:
        api._LOG_ERROR_BUFFER.clear()

    first = api._log_error_log_public(source="all", tb_limit=0, limit=5)
    second = api._log_error_log_public(source="all", tb_limit=0, limit=5)
    assert first == second
    assert calls["n"] == 0
