#!/usr/bin/env python3
"""PostgreSQL 逻辑备份（读取当前 Bot 的 PG_* / pallas.toml 配置）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pallas-Bot PostgreSQL 备份（pg_dump）")
    parser.add_argument(
        "-o",
        "--output-parent",
        default="",
        help="备份父目录（默认 <仓库>/backups；相对路径相对于仓库根）",
    )
    parser.add_argument("-l", "--label", default="", help="备份子目录名可选后缀")
    parser.add_argument(
        "-f",
        "--format",
        choices=("custom", "plain", "directory"),
        default="custom",
        help="pg_dump 格式：custom=.dump，plain=.sql，directory=目录格式",
    )
    args = parser.parse_args()
    from pallas.core.foundation.db.backup import run_postgres_backup

    parent = args.output_parent.strip() or None
    try:
        result = run_postgres_backup(
            output_parent=parent,
            label=args.label,
            pg_format=args.format,  # type: ignore[arg-type]
        )
    except Exception as e:
        print(f"备份失败: {e}", file=sys.stderr)
        return 1
    print(result.message)
    print(f"目录: {result.output_dir}")
    for art in result.artifacts:
        print(f"产物: {art}")
    print(f"大小: {result.size_bytes} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
