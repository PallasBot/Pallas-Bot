#!/usr/bin/env python3
"""按 PALLAS_SHARD_BOTS_PER / 注册表 bots_per_shard 重排生产分片 assignment。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.shard.registry.store import (  # noqa: E402
    clear_shard_registry_cache,
    rebalance_production_assignments,
)
from pallas.core.platform.shard.registry.sync_protocol_ports import (  # noqa: E402
    format_sync_user_message,
    sync_accounts_ws_urls,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="重排生产分片 assignment 并同步协议端 ws_url")
    parser.add_argument(
        "--accounts",
        type=Path,
        default=REPO_ROOT / "data/pallas_protocol/accounts.json",
    )
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--dry-run", action="store_true", help="只打印重排结果，不写注册表")
    parser.add_argument("--skip-port-sync", action="store_true")
    parser.add_argument(
        "--strategy",
        choices=("count", "activity"),
        default="count",
        help="count=按 bots_per_shard 均分；activity=按近期 worker stats 热度尽量摊平",
    )
    args = parser.parse_args()

    clear_shard_registry_cache()
    if args.dry_run:
        from pallas.core.platform.shard.registry.store import get_shard_registry

        reg = get_shard_registry()
        preview = rebalance_production_assignments(
            registry=reg.model_copy(deep=True),
            save=False,
            strategy=args.strategy,
        )
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    result = rebalance_production_assignments(strategy=args.strategy)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.skip_port_sync or not args.accounts.is_file():
        return 0

    sync_result = sync_accounts_ws_urls(
        args.accounts,
        env_path=args.env if args.env.is_file() else None,
    )
    if sync_result.changed_count or sync_result.onebot_drift_count:
        print(format_sync_user_message(sync_result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
