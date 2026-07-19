#!/usr/bin/env python3
"""启动前：按 worker 数量分配端口并写入 registry.json（可跳过占用端口）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.shard.registry.port_alloc import (  # noqa: E402
    sync_registry_worker_ports,
)
from pallas.core.platform.shard.registry.sync_protocol_ports import (  # noqa: E402
    apply_env_for_shard_sync,
    read_dotenv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="分配分片 worker 端口并写入 registry")
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--base", type=int, default=None, help="worker 起点端口")
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument(
        "--no-skip-occupied",
        action="store_true",
        help="严格使用 base+N，不跳过占用（可能启动失败）",
    )
    parser.add_argument("--quiet", action="store_true", help="仅输出逗号分隔端口列表")
    args = parser.parse_args()

    if args.env.is_file():
        apply_env_for_shard_sync(read_dotenv(args.env))

    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    from pallas.core.platform.shard.registry.store import clear_shard_registry_cache

    clear_shard_registry_cache()
    settings = get_shard_registry_settings()
    base = int(args.base if args.base is not None else settings.worker_base_port)

    try:
        result = sync_registry_worker_ports(
            args.workers,
            base,
            skip_occupied=not args.no_skip_occupied,
            persist=True,
        )
    except RuntimeError as err:
        print(f"端口分配失败: {err}", file=sys.stderr)
        return 1

    if not args.quiet:
        for _port, msg in result.skipped:
            print(f"  · {msg}", file=sys.stderr)

    print(",".join(str(p) for p in result.ports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
