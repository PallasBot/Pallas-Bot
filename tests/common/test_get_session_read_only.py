"""get_session(read_only=True) 应使用 AUTOCOMMIT，避免多段查询 idle in transaction。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeSession:
    def __init__(self) -> None:
        self.connection = AsyncMock(return_value=MagicMock())
        self.rollback = AsyncMock()
        self.close = AsyncMock()
        self.commit = AsyncMock()
        self.invalidate = AsyncMock()


@pytest.mark.asyncio
async def test_get_session_read_only_uses_autocommit(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    fake = _FakeSession()
    monkeypatch.setattr(mod, "_session_factory", lambda: fake)

    async with mod.get_session(read_only=True) as session:
        assert session is fake

    fake.connection.assert_awaited_once_with(execution_options={"isolation_level": "AUTOCOMMIT"})
    fake.rollback.assert_not_awaited()
    fake.close.assert_awaited_once()
    fake.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_session_write_rolls_back_on_exit(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    fake = _FakeSession()
    monkeypatch.setattr(mod, "_session_factory", lambda: fake)

    async with mod.get_session() as session:
        assert session is fake

    fake.connection.assert_not_awaited()
    fake.rollback.assert_awaited()
    fake.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_write_rolls_back_on_error(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    fake = _FakeSession()
    monkeypatch.setattr(mod, "_session_factory", lambda: fake)

    with pytest.raises(RuntimeError, match="boom"):
        async with mod.get_session():
            raise RuntimeError("boom")

    assert fake.rollback.await_count == 2
    fake.close.assert_awaited_once()


def test_pg_session_server_settings_defaults(monkeypatch):
    from pallas.core.foundation.db import pg_session_server_settings

    monkeypatch.delenv("PG_IDLE_IN_TRANSACTION_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("PG_APPLICATION_NAME", raising=False)

    settings = pg_session_server_settings()

    assert settings == {
        "application_name": "PallasBot",
        "idle_in_transaction_session_timeout": "15000",
    }


def test_pg_session_server_settings_respects_env(monkeypatch):
    from pallas.core.foundation.db import pg_session_server_settings

    monkeypatch.setenv("PG_IDLE_IN_TRANSACTION_TIMEOUT_MS", "25000")
    monkeypatch.setenv("PG_APPLICATION_NAME", "PallasBot-Worker")

    settings = pg_session_server_settings()

    assert settings == {
        "application_name": "PallasBot-Worker",
        "idle_in_transaction_session_timeout": "25000",
    }
