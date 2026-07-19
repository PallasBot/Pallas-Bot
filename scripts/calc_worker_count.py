#!/usr/bin/env python3
"""输出应启动的生产 worker 数量（供 run_sharded_bot.sh 调用）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.shard.registry.worker_count import calc_production_worker_count  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="计算生产 worker 数量")
    parser.add_argument("--bots-per", type=int, default=None)
    parser.add_argument("--base", type=int, default=None)
    parser.add_argument(
        "--accounts",
        type=Path,
        default=REPO_ROOT / "data/pallas_protocol/accounts.json",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=REPO_ROOT / "data/pallas_shard/registry.json",
    )
    args = parser.parse_args()
    bots_per = args.bots_per
    if bots_per is None:
        from pallas.core.platform.shard.registry.config import get_shard_registry_settings

        bots_per = get_shard_registry_settings().bots_per_shard
    count = calc_production_worker_count(
        bots_per_shard=bots_per,
        worker_base_port=args.base,
        accounts_path=args.accounts if args.accounts.is_file() else None,
        registry_path=args.registry if args.registry.is_file() else None,
    )
    print(count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
