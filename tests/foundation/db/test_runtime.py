from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pallas.core.foundation.db.runtime import (
    get_db_backend,
    is_mongodb_backend,
    is_postgresql_backend,
    normalize_db_backend_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mongodb", "mongodb"),
        ("mongo", "mongodb"),
        ("postgresql", "postgresql"),
        ("pg", "postgresql"),
        ("POSTGRES", "postgresql"),
        ("", "postgresql"),
        (None, "postgresql"),
    ],
)
def test_normalize_db_backend_name(raw: object, expected: str) -> None:
    assert normalize_db_backend_name(raw) == expected


def test_get_db_backend_defaults_to_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_BACKEND", raising=False)
    monkeypatch.setattr(
        "nonebot.get_driver",
        lambda: SimpleNamespace(config=SimpleNamespace()),
    )
    assert get_db_backend() == "postgresql"


def test_backend_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_BACKEND", "postgresql")
    assert is_postgresql_backend()
    assert not is_mongodb_backend()


def test_cfg_bool_parses_common_truthy() -> None:
    from pallas.core.foundation.db import _cfg_bool

    with patch("pallas.core.foundation.db._cfg", side_effect=lambda key, default="": "true"):
        assert _cfg_bool("PG_AUTO_CREATE_DB") is True
    with patch("pallas.core.foundation.db._cfg", side_effect=lambda key, default="": "0"):
        assert _cfg_bool("PG_AUTO_CREATE_DB") is False


@pytest.mark.asyncio
async def test_try_enable_pg_stat_statements_failure_does_not_raise() -> None:
    from pallas.core.foundation.db.repository_pg import try_enable_pg_stat_statements

    engine = MagicMock()
    begin_cm = AsyncMock()
    begin_cm.__aenter__.side_effect = RuntimeError("permission denied to create extension")
    begin_cm.__aexit__.return_value = None
    engine.begin.return_value = begin_cm

    assert await try_enable_pg_stat_statements(engine) is False


@pytest.mark.asyncio
async def test_init_postgresql_skips_auto_create_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.foundation import db as db_mod

    values = {
        "PG_HOST": "127.0.0.1",
        "PG_PORT": "5432",
        "PG_USER": "pallas",
        "PG_PASSWORD": "pallas",
        "PG_DB": "PallasBot",
        "PG_POOL_SIZE": "2",
        "PG_MAX_OVERFLOW": "1",
        "PG_POOL_RECYCLE": "1800",
        "PG_AUTO_CREATE_DB": "false",
    }
    monkeypatch.setattr(db_mod, "_cfg", lambda key, default="": values.get(key, default))

    urls: list[str] = []

    def fake_create_async_engine(url, **kwargs):
        urls.append(str(url))
        engine = MagicMock()
        engine.dispose = AsyncMock()
        return engine

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", side_effect=fake_create_async_engine),
        patch("pallas.core.foundation.db.repository_pg.init_pg", new_callable=AsyncMock) as init_pg,
        patch(
            "pallas.core.foundation.db.repository_pg.try_enable_pg_stat_statements",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("nonebot.get_driver", side_effect=RuntimeError("no driver")),
    ):
        await db_mod.init_postgresql_db()
        init_pg.assert_awaited_once()

    assert all("/postgres" not in url for url in urls)
    assert any(url.endswith("/PallasBot") for url in urls)
