from __future__ import annotations

import json

from src.platform.multi_bot import fleet as fleet_mod
from src.plugins.bot_status import list_mode as mod


class _Cfg:
    def __init__(self, list_mode: str = "auto"):
        self.bot_status_list_mode = list_mode


def patch_list_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setattr(mod, "get_bot_status_config", lambda: _Cfg(mode))


def patch_sharding(monkeypatch, active: bool) -> None:
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: active)


def test_resolve_auto_session_when_unified(monkeypatch):
    patch_sharding(monkeypatch, False)
    patch_list_mode(monkeypatch, "auto")
    assert mod.resolve_status_list_mode() == "session"


def test_resolve_auto_fleet_when_sharding(monkeypatch):
    patch_sharding(monkeypatch, True)
    patch_list_mode(monkeypatch, "auto")
    assert mod.resolve_status_list_mode() == "fleet"


def test_resolve_explicit_fleet_unified(monkeypatch):
    patch_sharding(monkeypatch, False)
    patch_list_mode(monkeypatch, "fleet")
    assert mod.resolve_status_list_mode() == "fleet"


def test_resolve_explicit_connected(monkeypatch):
    patch_sharding(monkeypatch, True)
    patch_list_mode(monkeypatch, "connected")
    assert mod.resolve_status_list_mode() == "connected"


def test_status_inventory_connected_uses_session_seen(monkeypatch):
    monkeypatch.setattr(mod, "get_session_seen_bot_ids", lambda: frozenset({222, 333}))
    ids = mod.status_inventory_bot_ids(list_mode="connected")
    assert ids == frozenset({222, 333})


def test_cluster_online_connected_uses_presence_when_sharding(monkeypatch):
    patch_sharding(monkeypatch, True)

    def fake_presence():
        return frozenset({100, 200})

    import src.platform.shard.presence as presence_mod

    monkeypatch.setattr(presence_mod, "get_cluster_online_bot_ids", fake_presence)
    online = mod.cluster_online_bot_ids_for_status(list_mode="connected")
    assert online == {100, 200}


def test_status_inventory_fleet_from_accounts(tmp_path, monkeypatch):
    proto = tmp_path / "pallas_protocol"
    proto.mkdir()
    acc = {"300": {"qq": "300", "enabled": True}}
    (proto / "accounts.json").write_text(json.dumps(acc), encoding="utf-8")

    monkeypatch.setattr(
        fleet_mod,
        "plugin_data_dir",
        lambda name: proto if name == "pallas_protocol" else tmp_path,
    )
    monkeypatch.setattr(fleet_mod, "is_sharding_active", lambda: False)
    fleet_mod.invalidate_fleet_bot_cache()
    patch_sharding(monkeypatch, False)

    ids = mod.status_inventory_bot_ids(list_mode="fleet")
    assert 300 in ids


def test_status_inventory_session_uses_block(monkeypatch):
    class FakeCfg:
        bots = {111}

    patch_sharding(monkeypatch, False)
    import src.plugins.block as block_mod

    monkeypatch.setattr(block_mod, "plugin_config", FakeCfg())
    ids = mod.status_inventory_bot_ids(list_mode="session")
    assert ids == frozenset({111})
