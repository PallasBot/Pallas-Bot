from __future__ import annotations

from unittest.mock import patch

from pallas.core.platform.shard.registry.port_alloc import (
    ports_still_in_use,
    wait_tcp_ports_free,
)


def test_ports_still_in_use_dedupes() -> None:
    with patch("pallas.core.platform.shard.registry.port_alloc.is_tcp_port_in_use", side_effect=[True, False]):
        assert ports_still_in_use([8090, 8090, 8091]) == [8090]


def test_wait_tcp_ports_free_immediate() -> None:
    with patch("pallas.core.platform.shard.registry.port_alloc.ports_still_in_use", return_value=[]):
        ok, busy = wait_tcp_ports_free([8090], timeout_sec=1.0)
    assert ok is True
    assert busy == []


def test_wait_tcp_ports_free_timeout() -> None:
    with patch("pallas.core.platform.shard.registry.port_alloc.ports_still_in_use", return_value=[8090]):
        ok, busy = wait_tcp_ports_free([8090], timeout_sec=0.2, poll_interval_sec=0.05)
    assert ok is False
    assert busy == [8090]
