#!/usr/bin/env python3
"""分片模式：按注册表同步协议端 accounts.json 的 ws_url（无变更则静默）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.shard.registry.sync_protocol_ports import (  # noqa: E402
    ProtocolPortSyncResult,
    format_sync_user_message,
    restore_accounts_file,
    sync_accounts_ws_urls,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="分片：同步协议端 accounts.json 的 ws_url 到各 worker 端口（无变更不输出）",
    )
    parser.add_argument(
        "--accounts",
        type=Path,
        default=REPO_ROOT / "data/pallas_protocol/accounts.json",
        help="accounts.json 路径",
    )
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env", help="读取分片相关环境变量")
    parser.add_argument(
        "--backup",
        type=Path,
        default=None,
        help="有变更时写入前备份到此路径（可选）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只检测变更，不写文件")
    parser.add_argument("--restore", type=Path, default=None, metavar="BACKUP", help="从备份恢复 accounts")
    parser.add_argument("--verbose", action="store_true", help="无变更时也打印一行说明")
    args = parser.parse_args()

    if args.restore is not None:
        restore_accounts_file(accounts_path=args.accounts, backup_path=args.restore)
        print(f"已恢复 {args.accounts} <- {args.restore}")
        return 0

    if not args.accounts.is_file():
        if args.verbose:
            print(f"未找到 {args.accounts}，跳过端口同步", file=sys.stderr)
        return 0

    try:
        result = sync_accounts_ws_urls(
            args.accounts,
            env_path=args.env if args.env.is_file() else None,
            backup_path=args.backup,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, ValueError, OSError) as err:
        print(f"协议端端口同步失败: {err}", file=sys.stderr)
        return 1

    if result.dry_run and result.changed_count > 0:
        print(format_sync_user_message(result, backup_path=None).replace("已更新", "[dry-run] 将更新"))
        return 0

    if result.changed_count == 0:
        if args.verbose:
            print("协议端 ws_url 已与分片注册表一致，无需修改。")
        return 0

    if not args.dry_run:
        print(format_sync_user_message(result, backup_path=args.backup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
