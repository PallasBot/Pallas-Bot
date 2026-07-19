from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_bot_admins_gate_cache(beanie_fixture, monkeypatch):
    from pallas.core.foundation.config import bot_admins_cache as cache
    from pallas.core.foundation.config import get_bot_admins
    from pallas.core.foundation.db import make_bot_config_repository

    await cache.reset_bot_admins_cache()
    repo = make_bot_config_repository()
    await repo.upsert_field(88001, "admins", [111, 222])

    calls: list[int] = []
    real_load = cache._load_admins_db

    async def counting_load(bot_id: int):
        calls.append(bot_id)
        return await real_load(bot_id)

    monkeypatch.setattr(cache, "_load_admins_db", counting_load)

    a = await get_bot_admins(88001)
    b = await get_bot_admins(88001)
    assert a == [111, 222]
    assert b == [111, 222]
    assert len(calls) == 1

    await cache.invalidate_bot_admins_cache(88001)
    c = await get_bot_admins(88001)
    assert c == [111, 222]
    assert len(calls) == 2

    await cache.reset_bot_admins_cache()


@pytest.mark.asyncio
async def test_get_bot_admins_cached_short_circuits_when_pg_not_ready(monkeypatch):
    from pallas.core.foundation.config import bot_admins_cache as cache

    await cache.reset_bot_admins_cache()

    async def fail_load(_bot_id: int):
        raise AssertionError("should not hit bot_admins db load when PG is not ready")

    monkeypatch.setattr(cache, "_load_admins_db", fail_load)
    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "postgresql")
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.is_pg_initialized", lambda: False)

    admins = await cache.get_bot_admins_cached(123456)
    assert admins == []


@pytest.mark.asyncio
async def test_any_bot_admin_user_ids_cached_short_circuits_when_pg_not_ready(monkeypatch):
    from pallas.core.foundation.config import bot_admins_cache as cache

    await cache.reset_bot_admins_cache()

    async def fail_load():
        raise AssertionError("should not hit cross-bot admins load when PG is not ready")

    monkeypatch.setattr(cache, "_load_any_bot_admin_user_ids", fail_load)
    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "postgresql")
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.is_pg_initialized", lambda: False)

    admins = await cache.any_bot_admin_user_ids_cached()
    assert admins == frozenset()


@pytest.mark.asyncio
async def test_get_bot_admins_skips_db_when_pool_under_pressure(monkeypatch):
    from pallas.core.foundation.config import bot_admins_cache as cache

    await cache.reset_bot_admins_cache()

    async def fail_load(_bot_id: int):
        raise AssertionError("should not load admins when pool is under pressure")

    monkeypatch.setattr(cache, "_load_admins_db", fail_load)
    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.pg_pool_under_pressure",
        lambda threshold=0.55: True,
    )

    admins = await cache.get_bot_admins_cached(123456)
    assert admins == []
