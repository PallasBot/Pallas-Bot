from __future__ import annotations

import pytest


def test_pg_init_failure_classifiers_distinguish_drop_vs_missing() -> None:
    from pallas.core.foundation.db import (
        _pg_init_failure_looks_like_dropped_connection,
        _pg_init_failure_looks_like_missing_db,
    )

    dropped = Exception(
        "<class 'asyncpg.exceptions.ConnectionDoesNotExistError'>: "
        "connection was closed in the middle of operation"
    )
    assert _pg_init_failure_looks_like_dropped_connection(dropped)
    assert not _pg_init_failure_looks_like_missing_db(dropped)

    missing = Exception('database "PallasBot" does not exist')
    assert not _pg_init_failure_looks_like_dropped_connection(missing)
    assert _pg_init_failure_looks_like_missing_db(missing)


@pytest.mark.asyncio
async def test_init_postgresql_db_skips_when_already_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    import pallas.core.foundation.db as db_mod

    calls: list[str] = []

    monkeypatch.setattr(
        "pallas.core.foundation.db.repository_pg.is_pg_initialized",
        lambda: True,
    )

    async def _init_pg_boom(*_a, **_k):
        calls.append("init_pg")
        raise AssertionError("should not re-init when already initialized")

    monkeypatch.setattr(
        "pallas.core.foundation.db.repository_pg.init_pg",
        _init_pg_boom,
    )

    await db_mod.init_postgresql_db()
    assert calls == []
