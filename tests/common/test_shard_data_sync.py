from __future__ import annotations

import json

from pallas.core.platform.multi_bot import fleet as fleet_mod
from pallas.core.platform.shard import data_sync as sync_mod
from pallas.core.platform.shard.registry import store as reg_mod


def test_refresh_on_accounts_mtime_change(tmp_path, monkeypatch):
    shard_root = tmp_path / "pallas_shard"
    shard_root.mkdir()
    (shard_root / "registry.json").write_text("{}", encoding="utf-8")

    proto = tmp_path / "pallas_protocol"
    proto.mkdir()
    acc_path = proto / "accounts.json"
    acc_path.write_text(json.dumps({"1": {"qq": "1", "enabled": True}}), encoding="utf-8")

    import pallas.core.platform.protocol_paths as proto_mod

    monkeypatch.setattr(proto_mod, "protocol_accounts_path", lambda *, create=False: acc_path)
    import pallas.core.foundation.paths as paths_mod

    monkeypatch.setattr(paths_mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(fleet_mod, "_accounts_path", lambda: acc_path)
    monkeypatch.setattr(reg_mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    import pallas.core.platform.shard.context as shard_ctx

    monkeypatch.setattr(shard_ctx, "sharding_active", lambda: True)

    sync_mod._seen = None
    fleet_mod.invalidate_fleet_bot_cache()
    fleet_mod._cached = frozenset({1})
    reg_mod._cached = object()  # type: ignore[assignment]

    assert sync_mod.refresh_shard_data_caches_if_stale() is True
    assert fleet_mod._cached is None
    assert reg_mod._cached is None

    reg_mod._cached = object()  # type: ignore[assignment]
    fleet_mod._cached = frozenset({2})
    assert sync_mod.refresh_shard_data_caches_if_stale() is False
