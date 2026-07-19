from __future__ import annotations

from pallas.core.platform.shard import context as ctx


def test_sharding_active_false_when_unified(monkeypatch) -> None:
    monkeypatch.delenv("PALLAS_SHARD_ENABLED", raising=False)
    monkeypatch.setenv("PALLAS_BOT_ROLE", "unified")
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    assert not ctx.sharding_active()
    assert ctx.is_unified()
    assert ctx.role() == "unified"


def test_sharding_active_true_for_worker(monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    monkeypatch.setenv("PALLAS_SHARD_ID", "2")
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    assert ctx.sharding_active()
    assert ctx.is_worker()
    assert ctx.shard_id() == 2
