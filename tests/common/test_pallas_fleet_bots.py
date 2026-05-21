from __future__ import annotations

import json

from src.common.multi_bot import fleet as mod


def test_load_enabled_account_qq(tmp_path, monkeypatch):
    proto = tmp_path / "pallas_protocol"
    proto.mkdir()
    acc = {
        "100": {"qq": "100", "enabled": False},
        "200": {"qq": "200", "enabled": True},
    }
    (proto / "accounts.json").write_text(json.dumps(acc), encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "plugin_data_dir",
        lambda name: proto if name == "pallas_protocol" else tmp_path,
    )
    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    mod.invalidate_fleet_bot_cache()
    ids = mod._load_fleet_bot_ids()
    assert 200 in ids
    assert 100 not in ids


def test_session_connected_merged_when_sharding(monkeypatch):
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "_load_enabled_account_qq", lambda: set())
    mod._session_connected.clear()
    mod.invalidate_fleet_bot_cache()
    mod.note_fleet_bot_session_connected(424242)
    ids = mod._load_fleet_bot_ids()
    assert 424242 in ids
    mod._session_connected.clear()
    mod.invalidate_fleet_bot_cache()


def test_get_catalog_bot_ids_non_shard_uses_block(monkeypatch):
    class FakeCfg:
        bots = {111, 222}

    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)

    import src.plugins.block as block_mod

    monkeypatch.setattr(block_mod, "plugin_config", FakeCfg())
    assert mod.get_catalog_bot_ids() == frozenset({111, 222})
