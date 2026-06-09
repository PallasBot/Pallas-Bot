from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_bot_disconnect_is_idempotent(monkeypatch) -> None:
    import src.plugins.block as mod

    plugin_config = SimpleNamespace(bots=set())
    disconnect_calls: list[int] = []
    info_calls: list[tuple[str, tuple[object, ...]]] = []

    async def clear_protocol_bot_offline(_qq: int) -> None:
        return None

    async def note_worker_bot_disconnected(qq: int) -> None:
        disconnect_calls.append(qq)

    monkeypatch.setattr(mod, "plugin_config", plugin_config)
    monkeypatch.setattr(mod, "clear_protocol_bot_offline", clear_protocol_bot_offline)
    monkeypatch.setattr(mod, "note_worker_bot_disconnected", note_worker_bot_disconnected)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: info_calls.append((msg, args)))

    bot = SimpleNamespace(self_id="1354970010", type="OneBot V11")

    await mod.bot_disconnect(bot)

    assert disconnect_calls == [1354970010]
    assert info_calls == []
