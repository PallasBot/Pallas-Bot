#!/usr/bin/env python3
"""等待 registry 中 worker 端口释放（用于 restart/stop 后、start 前）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.shard.registry.port_alloc import wait_tcp_ports_free  # noqa: E402


def ports_from_registry(registry_path: Path, worker_count: int) -> list[int]:
    if not registry_path.is_file():
        return []
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    by_id = {int(row["id"]): int(row["port"]) for row in (raw.get("shards") or []) if "id" in row}
    ports: list[int] = []
    for sid in range(max(0, int(worker_count))):
        if sid in by_id:
            ports.append(by_id[sid])
    return ports


def main() -> int:
    parser = argparse.ArgumentParser(description="等待分片 worker 端口释放")
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument(
        "--registry",
        type=Path,
        default=REPO_ROOT / "data/pallas_shard/registry.json",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    ports = ports_from_registry(args.registry, args.workers)
    if not ports:
        return 0

    ok, busy = wait_tcp_ports_free(
        ports,
        timeout_sec=args.timeout,
        poll_interval_sec=args.interval,
    )
    if ok:
        print(f"worker 端口已释放: {','.join(str(p) for p in ports)}", file=sys.stderr)
        return 0
    print(
        f"超时 ({args.timeout}s)：仍占用 {','.join(str(p) for p in busy)}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
