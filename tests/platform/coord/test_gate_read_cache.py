from __future__ import annotations

from unittest.mock import MagicMock

from pallas.core.platform.shard.coord.gate_read_cache import (
    gate_read_cache_get,
    reset_gate_read_cache_for_tests,
)


def test_gate_read_cache_reuses_loader_until_ttl(monkeypatch) -> None:
    reset_gate_read_cache_for_tests()
    monkeypatch.setenv("PALLAS_GATE_READ_CACHE_MS", "5000")
    loader = MagicMock(side_effect=[111, 222])
    assert gate_read_cache_get("owned:test:1", loader) == 111
    assert gate_read_cache_get("owned:test:1", loader) == 111
    loader.assert_called_once()


def test_gate_read_cache_invalidate_forces_reload(monkeypatch) -> None:
    from pallas.core.platform.shard.coord.gate_read_cache import gate_read_cache_invalidate

    reset_gate_read_cache_for_tests()
    monkeypatch.setenv("PALLAS_GATE_READ_CACHE_MS", "5000")
    loader = MagicMock(side_effect=[111, 222])
    gate_read_cache_get("owned:test:2", loader)
    gate_read_cache_invalidate("owned:test:2")
    assert gate_read_cache_get("owned:test:2", loader) == 222
    assert loader.call_count == 2
