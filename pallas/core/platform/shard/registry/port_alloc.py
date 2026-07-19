"""分片 worker 端口分配：从起点递增，可选跳过已被占用的 TCP 端口。"""

from __future__ import annotations

import socket
from typing import NamedTuple

from pallas.core.platform.shard.registry.store import (
    ShardRecord,
    ShardRegistry,
    get_shard_registry,
    save_shard_registry,
)


class PortAllocateResult(NamedTuple):
    ports: list[int]
    skipped: list[tuple[int, str]]


def is_tcp_port_in_use(port: int, *, host: str = "0.0.0.0") -> bool:
    if port < 1 or port > 65535:
        return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def allocate_worker_ports(
    worker_count: int,
    base_port: int,
    *,
    skip_occupied: bool = True,
    max_scan: int = 256,
) -> PortAllocateResult:
    """为 worker 0..N-1 分配端口；skip_occupied 时遇占用则向后找下一个空闲端口。"""
    n = max(0, int(worker_count))
    base = int(base_port)
    if n == 0:
        return PortAllocateResult(ports=[], skipped=[])
    ports: list[int] = []
    skipped: list[tuple[int, str]] = []
    candidate = base
    scanned = 0
    while len(ports) < n:
        if scanned > max_scan or candidate > 65535:
            msg = f"无法在 {base} 起向后 {max_scan} 个端口内为 {n} 个 worker 找齐空闲端口"
            raise RuntimeError(msg)
        scanned += 1
        nominal = base + len(ports)
        if skip_occupied and is_tcp_port_in_use(candidate):
            if candidate == nominal:
                skipped.append((candidate, f"worker-{len(ports)} 期望端口 {candidate} 已被占用"))
            candidate += 1
            continue
        if skip_occupied and candidate != nominal:
            skipped.append((nominal, f"worker-{len(ports)} 改用 {candidate}"))
        ports.append(candidate)
        candidate += 1
    return PortAllocateResult(ports=ports, skipped=skipped)


def worker_ports_from_registry(reg: ShardRegistry, worker_count: int) -> list[int] | None:
    if worker_count <= 0:
        return []
    by_id = {int(s.id): int(s.port) for s in reg.shards}
    ports: list[int] = []
    for sid in range(worker_count):
        if sid not in by_id:
            return None
        ports.append(by_id[sid])
    return ports


def all_worker_ports_free(ports: list[int]) -> bool:
    return all(not is_tcp_port_in_use(p) for p in ports)


def ports_still_in_use(ports: list[int]) -> list[int]:
    seen: set[int] = set()
    busy: list[int] = []
    for p in ports:
        pi = int(p)
        if pi in seen:
            continue
        seen.add(pi)
        if is_tcp_port_in_use(pi):
            busy.append(pi)
    return busy


def wait_tcp_ports_free(
    ports: list[int],
    *,
    timeout_sec: float = 60.0,
    poll_interval_sec: float = 0.5,
) -> tuple[bool, list[int]]:
    """轮询直至 ports 均可 bind 或超时。返回 (是否全部释放, 仍占用列表)。"""
    import time

    if not ports:
        return True, []
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    interval = max(0.1, float(poll_interval_sec))
    while True:
        busy = ports_still_in_use(ports)
        if not busy:
            return True, []
        if time.monotonic() >= deadline:
            return False, busy
        time.sleep(interval)


def apply_worker_ports_to_registry(
    reg: ShardRegistry,
    ports: list[int],
    *,
    worker_base_port: int | None = None,
) -> None:
    """将分配结果写入 registry.shards[].port。"""
    if worker_base_port is not None:
        reg.worker_base_port = int(worker_base_port)
    by_id = {s.id: s for s in reg.shards}
    for sid, port in enumerate(ports):
        if sid in by_id:
            by_id[sid].port = int(port)
        else:
            by_id[sid] = ShardRecord(id=sid, port=int(port), bot_ids=[])
    reg.shards = sorted(by_id.values(), key=lambda x: x.id)
    for s in reg.shards:
        if s.id < len(ports):
            s.port = ports[s.id]


def sync_registry_worker_ports(
    worker_count: int,
    base_port: int,
    *,
    skip_occupied: bool = True,
    persist: bool = True,
) -> PortAllocateResult:
    reg = get_shard_registry()
    result = allocate_worker_ports(worker_count, base_port, skip_occupied=skip_occupied)
    current = worker_ports_from_registry(reg, worker_count)
    if current == result.ports:
        return result
    apply_worker_ports_to_registry(reg, result.ports, worker_base_port=base_port)
    if persist:
        save_shard_registry(reg)
    return result
