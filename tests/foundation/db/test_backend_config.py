"""WebUI 数据库后端配置：读取掩码、落盘、探测。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pallas.core.foundation.db.backend_config import (
    build_backend_config_view,
    probe_db_backend,
    save_db_backend_config,
)


def test_build_backend_config_view_masks_password(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "DB_BACKEND": "postgresql",
        "PG_HOST": "127.0.0.1",
        "PG_PORT": "5432",
        "PG_USER": "pallas",
        "PG_PASSWORD": "secret-pw",
        "PG_DB": "PallasBot",
        "PG_AUTO_CREATE_DB": "false",
    }
    monkeypatch.setattr(
        "pallas.core.foundation.db.backend_config.repo_env_raw_value",
        lambda key: values.get(key),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.backend_config.get_db_backend",
        lambda: "postgresql",
    )

    view = build_backend_config_view()
    assert view["active_backend"] == "postgresql"
    assert view["backend"] == "postgresql"
    assert view["postgres"]["password"] == ""
    assert view["postgres"]["password_set"] is True
    assert "secret-pw" not in str(view)


def test_save_db_backend_config_skips_empty_password(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[str, str] = {}

    monkeypatch.setattr(
        "pallas.core.foundation.db.backend_config.repo_env_raw_value",
        lambda key: "existing-secret" if key == "PG_PASSWORD" else None,
    )

    def fake_upsert(items: dict[str, str]) -> None:
        saved.update(items)

    monkeypatch.setattr(
        "pallas.core.foundation.db.backend_config.upsert_env_dotenv_items",
        fake_upsert,
    )

    result = save_db_backend_config({
        "backend": "postgresql",
        "postgres": {
            "host": "db.example",
            "port": 5432,
            "user": "pallas",
            "password": "",
            "db": "PallasBot",
            "auto_create_db": False,
        },
    })
    assert result["restart_required"] is True
    assert saved["DB_BACKEND"] == "postgresql"
    assert saved["PG_HOST"] == "db.example"
    assert "PG_PASSWORD" not in saved


def test_save_db_backend_config_writes_password_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[str, str] = {}
    monkeypatch.setattr(
        "pallas.core.foundation.db.backend_config.repo_env_raw_value",
        lambda _key: None,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.backend_config.upsert_env_dotenv_items",
        lambda items: saved.update(items),
    )

    save_db_backend_config({
        "backend": "mongodb",
        "mongo": {
            "host": "mongo.example",
            "port": 27017,
            "user": "u",
            "password": "new-secret",
            "db": "PallasBot",
            "auth_source": "admin",
        },
    })
    assert saved["DB_BACKEND"] == "mongodb"
    assert saved["MONGO_PASSWORD"] == "new-secret"
    assert saved["MONGO_AUTH_SOURCE"] == "admin"


@pytest.mark.asyncio
async def test_probe_postgresql_success() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock()
    engine = MagicMock()
    engine.connect.return_value.__aenter__ = AsyncMock(return_value=conn)
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)
    engine.dispose = AsyncMock()

    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        return_value=engine,
    ):
        result = await probe_db_backend({
            "backend": "postgresql",
            "postgres": {
                "host": "127.0.0.1",
                "port": 5432,
                "user": "pallas",
                "password": "pallas",
                "db": "PallasBot",
            },
        })
    assert result["ok"] is True
    assert result["latency_ms"] >= 0
    engine.dispose.assert_awaited()


@pytest.mark.asyncio
async def test_probe_failure_returns_ok_false_without_password() -> None:
    with patch(
        "sqlalchemy.ext.asyncio.create_async_engine",
        side_effect=RuntimeError("connection refused password=should-not-leak"),
    ):
        result = await probe_db_backend({
            "backend": "postgresql",
            "postgres": {
                "host": "bad.host",
                "port": 5432,
                "user": "pallas",
                "password": "should-not-leak",
                "db": "PallasBot",
            },
        })
    assert result["ok"] is False
    assert "should-not-leak" not in result["detail"]


def test_save_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="不支持"):
        save_db_backend_config({"backend": "sqlite"})
