from __future__ import annotations

from src.common.shard.coord import duel_group as mod


def test_duel_group_lock_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_coord_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )

    assert mod.try_begin_duel_group(10086) is True
    assert mod.try_begin_duel_group(10086) is False
    mod.end_duel_group(10086)
    assert mod.try_begin_duel_group(10086) is True


def test_duel_group_local_fallback(monkeypatch):
    monkeypatch.setattr(mod, "is_sharding_active", lambda: False)
    mod._local_busy.clear()
    assert mod.try_begin_duel_group(1) is True
    assert mod.try_begin_duel_group(1) is False
    mod.end_duel_group(1)
    assert mod.try_begin_duel_group(1) is True
    mod.end_duel_group(1)
