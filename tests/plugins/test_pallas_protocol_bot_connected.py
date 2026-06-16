from __future__ import annotations

from src.plugins.pb_protocol.service import PallasProtocolService


def _service() -> PallasProtocolService:
    return object.__new__(PallasProtocolService)


def test_is_bot_connected_hub_uses_cluster_presence(monkeypatch) -> None:
    svc = _service()
    monkeypatch.setattr("src.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("src.platform.shard.context.is_hub", lambda: True)
    monkeypatch.setattr(
        "src.platform.shard.presence.get_cluster_online_bot_ids",
        lambda: frozenset({111, 222}),
    )

    assert svc._is_bot_connected({"qq": "111"}) is True
    assert svc._is_bot_connected({"id": "222"}) is True
    assert svc._is_bot_connected({"qq": "999"}) is False


def test_is_bot_connected_non_hub_uses_get_bots(monkeypatch) -> None:
    svc = _service()
    monkeypatch.setattr(
        "src.platform.shard.registry.config.is_sharding_active",
        lambda: False,
    )
    monkeypatch.setattr("nonebot.get_bots", lambda: {"333": object()})

    assert svc._is_bot_connected({"qq": "333"}) is True
    assert svc._is_bot_connected({"qq": "444"}) is False
