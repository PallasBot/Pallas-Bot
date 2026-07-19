import pytest

from pallas.core.foundation.db.pool_budget import (
    cap_by_pg_pool,
    clear_pool_budget_runtime_cache,
    pg_pool_capacity,
    pg_pool_snapshot,
    pg_pool_under_pressure,
    remote_corpus_concurrency_limit,
)


@pytest.fixture(autouse=True)
def clear_pool_budget_cache():
    clear_pool_budget_runtime_cache()
    yield
    clear_pool_budget_runtime_cache()


def test_cap_by_pg_pool_respects_fraction(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.repo_env_raw_value",
        lambda key: {"PG_POOL_SIZE": "48", "PG_MAX_OVERFLOW": "24"}.get(key),
    )
    assert pg_pool_capacity() == 72
    assert cap_by_pg_pool(24, workload_fraction=0.22) == 15
    assert cap_by_pg_pool(8, workload_fraction=0.28) == 8


def test_remote_corpus_limit_from_pool(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.repo_env_raw_value",
        lambda key: {"PG_POOL_SIZE": "48", "PG_MAX_OVERFLOW": "24"}.get(key),
    )
    assert remote_corpus_concurrency_limit() == 7

    def with_override(key: str):
        if key == "PALLAS_CORPUS_REMOTE_MAX_CONCURRENT":
            return "4"
        return {"PG_POOL_SIZE": "48", "PG_MAX_OVERFLOW": "24"}.get(key)

    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.repo_env_raw_value", with_override)
    assert remote_corpus_concurrency_limit() == 4


def test_pg_pool_snapshot_cached_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_live_stats():
        calls["n"] += 1
        return {"checked_out": 3, "overflow": 0, "capacity": 10}

    monkeypatch.setattr(
        "pallas.core.foundation.db.repository_pg.pg_pool_live_stats",
        fake_live_stats,
    )
    clear_pool_budget_runtime_cache()
    assert pg_pool_snapshot() == {"checked_out": 3, "overflow": 0, "capacity": 10}
    assert pg_pool_snapshot() == {"checked_out": 3, "overflow": 0, "capacity": 10}
    assert calls["n"] == 1
    assert pg_pool_under_pressure(threshold=0.25) is True


def test_pg_pool_capacity_cached_until_disk_revision(monkeypatch):
    values = {"PG_POOL_SIZE": "8", "PG_MAX_OVERFLOW": "4"}

    def fake_env(key: str):
        return values.get(key)

    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.repo_env_raw_value", fake_env)
    rev = {"v": ((1, 1),)}

    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.repo_settings_disk_revision", lambda: rev["v"])
    clear_pool_budget_runtime_cache()
    assert pg_pool_capacity() == 12
    assert pg_pool_capacity() == 12
    values["PG_POOL_SIZE"] = "10"
    assert pg_pool_capacity() == 12
    rev["v"] = ((2, 2),)
    assert pg_pool_capacity() == 14
