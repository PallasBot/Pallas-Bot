from __future__ import annotations

from pallas.core.platform.shard.observability import pg_pool_estimate


def test_pg_pool_estimate_no_warn_at_28_times_9(monkeypatch):
    def fake_env(key: str):
        return {"PG_POOL_SIZE": "16", "PG_MAX_OVERFLOW": "12"}.get(key)

    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        fake_env,
    )
    monkeypatch.setattr("pallas.core.platform.shard.observability.is_sharding_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.observability.get_shard_registry",
        lambda: type("R", (), {"shards": list(range(8))})(),
    )
    info = pg_pool_estimate()
    assert info["estimated_pg_connections_peak"] == 252
    assert info["warning"] is None


def test_pg_pool_estimate_warns_when_oversized(monkeypatch):
    def fake_env(key: str):
        return {"PG_POOL_SIZE": "400", "PG_MAX_OVERFLOW": "400"}.get(key)

    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        fake_env,
    )
    monkeypatch.setattr("pallas.core.platform.shard.observability.is_sharding_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.shard.observability.get_shard_registry",
        lambda: type("R", (), {"shards": [1, 2, 3, 4, 5, 6, 7, 8]})(),
    )
    info = pg_pool_estimate()
    assert info["estimated_pg_connections_peak"] == 7200
    assert info["warning"] is not None
