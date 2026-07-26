#!/usr/bin/env python3
"""分片启停：识别本仓库 bot_hub / bot_worker 孤儿进程与 TCP 监听者。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.console.cli.shard_guard import guard_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(guard_main())
