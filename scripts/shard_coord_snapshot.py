#!/usr/bin/env python3
"""coord Redis 键空间快照（coord 已 Redis 化，无文件可清理）。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description="coord Redis 模式快照（legacy 文件清理已停用）")
    parser.add_argument(
        "--purge-done",
        action="store_true",
        help="兼容旧参数；Redis 模式下无文件可清理",
    )
    parser.add_argument(
        "--live-scan",
        action="store_true",
        help="显式扫描 Redis 键空间；默认仅输出轻量快照",
    )
    args = parser.parse_args()
    from src.platform.shard.coord_pending import coord_pending_snapshot_sync

    snap = coord_pending_snapshot_sync(live=bool(args.live_scan))
    out = {
        "storage": snap.get("storage"),
        "snapshot": snap,
        "purge_done_requested": bool(args.purge_done),
        "live_scan_requested": bool(args.live_scan),
        "note": "coord 数据存 Redis，无 JSON 文件轮询/prune",
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
