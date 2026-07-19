#!/usr/bin/env python3
"""按当前 DB_BACKEND 备份 MongoDB 或 PostgreSQL。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pallas-Bot 数据库备份")
    parser.add_argument("-o", "--output-parent", default="", help="备份父目录")
    parser.add_argument("-l", "--label", default="", help="备份目录名后缀")
    parser.add_argument(
        "--scope",
        choices=("full", "important"),
        default="full",
        help="MongoDB：full=整库，important=关键集合",
    )
    parser.add_argument(
        "-f",
        "--pg-format",
        choices=("custom", "plain", "directory"),
        default="custom",
        help="PostgreSQL pg_dump 格式",
    )
    args = parser.parse_args()
    from pallas.core.foundation.db.backup import run_database_backup

    try:
        result = run_database_backup(
            output_parent=args.output_parent.strip() or None,
            label=args.label,
            scope=args.scope,  # type: ignore[arg-type]
            pg_format=args.pg_format,  # type: ignore[arg-type]
        )
    except Exception as e:
        print(f"备份失败: {e}", file=sys.stderr)
        return 1
    print(result.message)
    print(f"后端: {result.backend}  范围: {result.scope}")
    print(f"目录: {result.output_dir}")
    for art in result.artifacts:
        print(f"产物: {art}")
    print(f"大小: {result.size_bytes} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
