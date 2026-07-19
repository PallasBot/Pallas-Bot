from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.core.platform.multi_bot import connected_roster as mod


@pytest.mark.asyncio
async def test_bot_connect_ensures_runtime_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._connected_bots.clear()
    ensure_calls: list[int] = []
    info_calls: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def ensure_bot_runtime_storage(qq: int) -> bool:
        ensure_calls.append(qq)
        return True

    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "ensure_bot_runtime_storage", ensure_bot_runtime_storage)
    monkeypatch.setattr(mod, "note_bot_session_seen", lambda _qq: None)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_calls.append((msg, args)))

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.on_bot_connect(bot)

    assert ensure_calls == [1354970010]
    assert ("Bot {} runtime storage initialized on connect.", ("1354970010",)) in info_calls


@pytest.mark.asyncio
async def test_bot_connect_logs_when_runtime_storage_already_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._connected_bots.clear()
    info_calls: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def ensure_bot_runtime_storage(_qq: int) -> bool:
        return False

    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "ensure_bot_runtime_storage", ensure_bot_runtime_storage)
    monkeypatch.setattr(mod, "note_bot_session_seen", lambda _qq: None)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_calls.append((msg, args)))

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.on_bot_connect(bot)

    assert ("Bot {} runtime storage already ready on connect.", ("1354970010",)) in info_calls


@pytest.mark.asyncio
async def test_bot_connect_ignores_runtime_storage_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._connected_bots.clear()
    warnings: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def ensure_bot_runtime_storage(_qq: int) -> bool:
        raise RuntimeError("boom")

    async def ensure_bot_config_row(_qq: int) -> bool:
        return False

    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "ensure_bot_runtime_storage", ensure_bot_runtime_storage)
    monkeypatch.setattr(mod, "ensure_bot_config_row", ensure_bot_config_row)
    monkeypatch.setattr(mod, "note_bot_session_seen", lambda _qq: None)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append((msg, args)))

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.on_bot_connect(bot)

    assert 1354970010 in mod.connected_bot_ids()
    assert len(warnings) == 1
    msg, args = warnings[0]
    assert msg == "Bot {} runtime storage ensure failed: {}"
    assert args[0] == "1354970010"
    assert str(args[1]) == "boom"


@pytest.mark.asyncio
async def test_bot_connect_ensures_bot_config_row(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._connected_bots.clear()
    ensure_calls: list[int] = []
    info_calls: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def ensure_bot_runtime_storage(_qq: int) -> bool:
        return False

    async def ensure_bot_config_row(qq: int) -> bool:
        ensure_calls.append(qq)
        return True

    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "ensure_bot_runtime_storage", ensure_bot_runtime_storage)
    monkeypatch.setattr(mod, "ensure_bot_config_row", ensure_bot_config_row)
    monkeypatch.setattr(mod, "note_bot_session_seen", lambda _qq: None)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_calls.append((msg, args)))
    monkeypatch.setattr(mod.logger, "debug", lambda *_args, **_kwargs: None)

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.on_bot_connect(bot)

    assert ensure_calls == [1354970010]
    assert ("bot_config ensured for Bot {}", ("1354970010",)) in info_calls


@pytest.mark.asyncio
async def test_bot_connect_ignores_bot_config_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._connected_bots.clear()
    warnings: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def ensure_bot_runtime_storage(_qq: int) -> bool:
        return False

    async def ensure_bot_config_row(_qq: int) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "ensure_bot_runtime_storage", ensure_bot_runtime_storage)
    monkeypatch.setattr(mod, "ensure_bot_config_row", ensure_bot_config_row)
    monkeypatch.setattr(mod, "note_bot_session_seen", lambda _qq: None)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.logger, "info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod.logger, "debug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append((msg, args)))

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.on_bot_connect(bot)

    assert 1354970010 in mod.connected_bot_ids()
    assert len(warnings) == 1
    msg, args = warnings[0]
    assert msg == "Bot {} bot_config ensure failed: {}"
    assert args[0] == "1354970010"
    assert str(args[1]) == "db down"


@pytest.mark.asyncio
async def test_bot_disconnect_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    mod._connected_bots.clear()
    disconnect_calls: list[int] = []
    info_calls: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def note_worker_bot_disconnected(qq: int) -> None:
        disconnect_calls.append(qq)

    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "note_worker_bot_disconnected", note_worker_bot_disconnected)
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_calls.append((msg, args)))

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.on_bot_disconnect(bot)

    assert disconnect_calls == [1354970010]
    assert info_calls == []
