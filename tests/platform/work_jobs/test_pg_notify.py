from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.work_jobs import pg_notify


@pytest.mark.asyncio
async def test_notify_delivery_ready_uses_injected_impl(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_impl() -> None:
        calls.append("notified")

    monkeypatch.setattr(pg_notify, "_notify_impl", fake_impl)
    await pg_notify.notify_delivery_ready()
    assert calls == ["notified"]


@pytest.mark.asyncio
async def test_set_notify_delivery_ready_impl_roundtrip(monkeypatch) -> None:
    async def impl() -> None:
        pass

    monkeypatch.setattr(pg_notify, "_notify_impl", None)
    pg_notify.set_notify_delivery_ready_impl(impl)
    try:
        assert pg_notify._notify_impl is impl
    finally:
        pg_notify.set_notify_delivery_ready_impl(None)
    assert pg_notify._notify_impl is None


def test_channel_name_is_delivery_ready() -> None:
    assert pg_notify.DELIVERY_READY_CHANNEL == "sticker_vision.delivery_ready"


def _fake_pg_setup(*, backend: str) -> tuple[MagicMock, MagicMock, dict]:
    engine = MagicMock()
    # 记录 add_listener 收到的 channel 与 wrapper，供测试手动回调
    captured: dict[str, object | MagicMock] = {}
    add_listener = AsyncMock(side_effect=lambda channel, wrapper: captured.update(channel=channel, wrapper=wrapper))
    remove_listener = AsyncMock()

    asyncpg_conn = MagicMock()
    asyncpg_conn.add_listener = add_listener
    asyncpg_conn.remove_listener = remove_listener

    raw = MagicMock()
    raw.driver_connection = asyncpg_conn

    engine.raw_connection = AsyncMock(return_value=raw)
    return engine, raw, captured


@pytest.mark.asyncio
async def test_listen_delivery_ready_listens_on_channel_and_invokes_callback(monkeypatch) -> None:
    engine, raw, captured = _fake_pg_setup(backend="postgresql")
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.pg_engine", lambda: engine)
    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "postgresql")

    notified = AsyncMock()
    task = asyncio.create_task(pg_notify.listen_delivery_ready(notified))
    try:
        await asyncio.sleep(0)
        assert captured["channel"] == pg_notify.DELIVERY_READY_CHANNEL
        await captured["wrapper"](asyncpg_conn=None, pid=123, channel=pg_notify.DELIVERY_READY_CHANNEL, payload="1")
        await asyncio.sleep(0)
        notified.assert_awaited_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_listen_delivery_ready_skips_when_backend_not_postgresql(monkeypatch) -> None:
    engine, raw, captured = _fake_pg_setup(backend="mongodb")
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.pg_engine", lambda: engine)
    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "mongodb")

    await pg_notify.listen_delivery_ready(None)
    engine.raw_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_delivery_ready_skips_when_pg_engine_not_initialized(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.pg_engine", lambda: None)
    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "postgresql")

    await pg_notify.listen_delivery_ready(None)
