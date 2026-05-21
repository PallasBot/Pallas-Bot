from __future__ import annotations

import json

from src.common.multi_bot import fleet as fleet_mod
from src.plugins.bot_status import list_mode as mod


class _Cfg:
    def __init__(self, list_mode: str = "auto"):
        self.bot_status_list_mode = list_mode


def patch_list_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setattr(mod, "get_bot_status_config", lambda: _Cfg(mode))


def test_resolve_auto_session_when_unified(monkeypatch):
    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    patch_list_mode(monkeypatch, "auto")
    assert mod.resolve_status_list_mode() == "session"


def test_resolve_auto_fleet_when_sharding(monkeypatch):
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    patch_list_mode(monkeypatch, "auto")
    assert mod.resolve_status_list_mode() == "fleet"


def test_resolve_explicit_fleet_unified(monkeypatch):
    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    patch_list_mode(monkeypatch, "fleet")
    assert mod.resolve_status_list_mode() == "fleet"


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
    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)

    ids = mod.status_inventory_bot_ids(list_mode="fleet")
    assert 300 in ids


def test_status_inventory_session_uses_block(monkeypatch):
    class FakeCfg:
        bots = {111}

    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    import src.plugins.block as block_mod

    monkeypatch.setattr(block_mod, "plugin_config", FakeCfg())
    ids = mod.status_inventory_bot_ids(list_mode="session")
    assert ids == frozenset({111})
