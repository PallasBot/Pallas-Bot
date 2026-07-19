#!/usr/bin/env python3
"""应用 ``deploy/`` 下的可选部署模板（合并配置片段并记录落盘标记）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.console.cli.deploy_ops import apply_deploy_profile  # noqa: E402
from pallas.core.foundation.deploy_profile import DEPLOY_PROFILES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile",
        choices=sorted(DEPLOY_PROFILES.keys()),
        help="部署模板 id",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将写入的 env 键与 uv 命令")
    args = parser.parse_args()
    return apply_deploy_profile(args.profile, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
