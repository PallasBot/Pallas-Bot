from __future__ import annotations

import json

from src.platform.multi_bot import session_seen as mod


def test_note_and_load_cluster_seen(tmp_path, monkeypatch):
    from src.platform.multi_bot import fleet as fleet_mod

    shard_dir = tmp_path / "pallas_shard"
    shard_dir.mkdir()
    monkeypatch.setattr(
        mod,
        "plugin_data_dir",
        lambda name, create=False: shard_dir if name == "pallas_shard" else tmp_path,
    )
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(fleet_mod, "get_enabled_protocol_bot_ids", lambda: frozenset({111, 222}))

    mod.note_cluster_session_seen_sync(qq=111)
    mod.note_cluster_session_seen_sync(qq=222)
    mod.note_cluster_session_seen_sync(qq=111)

    assert mod.get_session_seen_bot_ids() == frozenset({111, 222})

    raw = json.loads((shard_dir / "cluster_session_seen.json").read_text(encoding="utf-8"))
    assert set(raw["seen"]) == {"111", "222"}


def test_unified_session_seen_from_fleet_memory(monkeypatch):
    from src.platform.multi_bot import fleet as fleet_mod

    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    monkeypatch.setattr(fleet_mod, "get_enabled_protocol_bot_ids", lambda: frozenset({999}))
    fleet_mod.invalidate_fleet_bot_cache()
    fleet_mod.note_fleet_bot_session_connected(999)

    assert mod.get_session_seen_bot_ids() == frozenset({999})


def test_session_seen_intersects_enabled_protocol(monkeypatch):
    from src.platform.multi_bot import fleet as fleet_mod

    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    monkeypatch.setattr(fleet_mod, "get_enabled_protocol_bot_ids", lambda: frozenset({100}))
    fleet_mod._session_connected.clear()
    fleet_mod.note_fleet_bot_session_connected(100)
    fleet_mod.note_fleet_bot_session_connected(200)

    assert mod.get_session_seen_bot_ids() == frozenset({100})
    fleet_mod._session_connected.clear()


def test_duplicate_cluster_seen_does_not_rewrite_file(tmp_path, monkeypatch):
    shard_dir = tmp_path / "pallas_shard"
    shard_dir.mkdir()
    monkeypatch.setattr(
        mod,
        "plugin_data_dir",
        lambda name, create=False: shard_dir if name == "pallas_shard" else tmp_path,
    )

    writes: list[dict[str, object]] = []
    real_write = mod._write_seen_atomic

    def wrapped(data):
        writes.append(dict(data))
        real_write(data)

    monkeypatch.setattr(mod, "_write_seen_atomic", wrapped)

    mod.note_cluster_session_seen_sync(qq=111)
    mod.note_cluster_session_seen_sync(qq=111)

    assert len(writes) == 1
