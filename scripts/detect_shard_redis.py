#!/usr/bin/env python3
"""分片启动前探测 Redis：可 ping 则输出 PALLAS_COORD_REDIS_* 供 run_sharded_bot.sh 注入。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def redis_package_installed() -> bool:
    try:
        import redis  # noqa: F401

        return True
    except ImportError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect Redis for shard coord claims")
    parser.add_argument("--quiet", action="store_true", help="No stderr hints")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print key=value status lines for run_sharded_bot.sh status",
    )
    args = parser.parse_args()

    from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ

    apply_repo_settings_to_environ()

    from pallas.core.platform.coord.redis_settings import (
        clear_coord_redis_settings_cache,
        coord_redis_enabled,
        coord_redis_mode,
        resolve_coord_redis_url,
    )

    clear_coord_redis_settings_cache()
    mode = coord_redis_mode()
    url = resolve_coord_redis_url() or ""
    pkg = "yes" if redis_package_installed() else "no"
    reachable = "yes" if url and coord_redis_enabled() else "no"
    active = "yes" if reachable == "yes" else "no"
    backend = "redis" if active == "yes" else "unavailable"

    if args.status:
        print(f"policy={mode}")
        print(f"url={url}")
        print(f"package={pkg}")
        print(f"reachable={reachable}")
        print(f"active={active}")
        print(f"backend={backend}")
        return 0

    if mode == "false":
        if not args.quiet:
            print("coord redis: disabled (PALLAS_COORD_REDIS_ENABLED=false)", file=sys.stderr)
        return 0

    if not url:
        if not args.quiet:
            print(
                "coord redis: no REDIS_URL in config/pallas.toml [env] or webui.json",
                file=sys.stderr,
            )
        return 0

    if coord_redis_enabled():
        print("PALLAS_COORD_REDIS_ENABLED=true")
        print(f"PALLAS_COORD_REDIS_URL={url}")
        if not args.quiet:
            print(f"coord redis: using {url}", file=sys.stderr)
        return 0

    if mode == "true":
        if not args.quiet:
            print("coord redis: forced on but unreachable; sharding claims will fail", file=sys.stderr)
        return 1

    if not args.quiet:
        if pkg == "no":
            print(
                "coord redis: URL set but package missing; run: uv sync --extra coord-redis",
                file=sys.stderr,
            )
        else:
            print(f"coord redis: unreachable ({url}); sharding claims will fail", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
