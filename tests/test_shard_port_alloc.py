"""分片 worker 端口分配。"""

from unittest.mock import patch

from src.common.shard.registry.port_alloc import (
    allocate_worker_ports,
    apply_worker_ports_to_registry,
)
from src.common.shard.registry.store import ShardRegistry


def test_allocate_strict_base_plus_index():
    result = allocate_worker_ports(3, 8090, skip_occupied=False)
    assert result.ports == [8090, 8091, 8092]
    assert result.skipped == []


def test_allocate_skips_occupied():
    used = {8090, 8092}

    def fake_in_use(port: int, *, host: str = "0.0.0.0") -> bool:
        return port in used

    with patch("src.common.shard.registry.port_alloc.is_tcp_port_in_use", side_effect=fake_in_use):
        result = allocate_worker_ports(3, 8090, skip_occupied=True)
    assert result.ports == [8091, 8093, 8094]


def test_apply_worker_ports_to_registry():
    reg = ShardRegistry(worker_base_port=8090, shards=[])
    apply_worker_ports_to_registry(reg, [8090, 8091, 8097], worker_base_port=8090)
    assert [s.port for s in reg.shards if s.id in (0, 1, 2)] == [8090, 8091, 8097]
