#!/usr/bin/env python3
"""分片 start 前：分配 worker 端口写回 registry，再按最终 registry 评估/同步协议端。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.platform.shard.registry.port_alloc import (  # noqa: E402
    sync_registry_worker_ports,
    worker_ports_from_registry,
)
from src.platform.shard.registry.startup_ports import (  # noqa: E402
    evaluate_protocol_port_sync,
    evaluate_registry_worker_ports,
)
from src.platform.shard.registry.store import clear_shard_registry_cache, get_shard_registry  # noqa: E402
from src.platform.shard.registry.sync_protocol_ports import (  # noqa: E402
    format_sync_user_message,
    sync_accounts_ws_urls,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="分片启动前端口准备")
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--base", type=int, default=None)
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument(
        "--accounts",
        type=Path,
        default=REPO_ROOT / "data/pallas_protocol/accounts.json",
    )
    parser.add_argument("--backup", type=Path, default=None)
    parser.add_argument(
        "--no-skip-occupied",
        action="store_true",
        help="严格 base+N，不因占用改端口",
    )
    parser.add_argument("--skip-protocol-sync", action="store_true")
    args = parser.parse_args()

    skip_occupied = not args.no_skip_occupied
    env_path = args.env if args.env.is_file() else None
    accounts_path = args.accounts if args.accounts.is_file() else None

    from src.platform.shard.registry.config import get_shard_registry_settings

    if env_path is not None:
        from src.platform.shard.registry.sync_protocol_ports import apply_env_for_shard_sync, read_dotenv

        apply_env_for_shard_sync(read_dotenv(env_path))
        get_shard_registry_settings.cache_clear()
        clear_shard_registry_cache()

    base = int(args.base if args.base is not None else get_shard_registry_settings().worker_base_port)

    reg_ev = evaluate_registry_worker_ports(
        args.workers,
        base,
        env_path=env_path,
        skip_occupied=skip_occupied,
    )
    for note in reg_ev.notes:
        print(f"  · {note}", file=sys.stderr)

    worker_ports = list(reg_ev.worker_ports)
    if not reg_ev.skip_registry_alloc:
        result = sync_registry_worker_ports(
            args.workers,
            base,
            skip_occupied=skip_occupied,
            persist=True,
        )
        for _port, msg in result.skipped:
            print(f"  · {msg}", file=sys.stderr)
        clear_shard_registry_cache()
        final = worker_ports_from_registry(get_shard_registry(), args.workers)
        worker_ports = final if final is not None else result.ports

    if reg_ev.skip_registry_alloc:
        print("skip_registry=yes", file=sys.stderr)

    proto_ev = evaluate_protocol_port_sync(accounts_path=accounts_path, env_path=env_path)
    for note in proto_ev.notes:
        print(f"  · {note}", file=sys.stderr)

    if (
        not args.skip_protocol_sync
        and accounts_path is not None
        and not proto_ev.skip_protocol_sync
    ):
        sync_result = sync_accounts_ws_urls(
            accounts_path,
            env_path=env_path,
            backup_path=args.backup,
            dry_run=False,
        )
        if sync_result.changed_count or sync_result.onebot_synced_count:
            print(format_sync_user_message(sync_result, backup_path=args.backup), file=sys.stderr)

    if proto_ev.skip_protocol_sync or args.skip_protocol_sync:
        print("skip_protocol=yes", file=sys.stderr)

    print(",".join(str(p) for p in worker_ports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
