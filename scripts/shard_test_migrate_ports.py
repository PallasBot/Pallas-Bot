#!/usr/bin/env python3
"""分片测试：备份并按注册表改写协议端 accounts.json（调用 sync_shard_protocol_ports 核心）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.shard.registry.sync_protocol_ports import (  # noqa: E402
    restore_accounts_file,
    sync_accounts_ws_urls,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="分片测试：协议端 ws_url 端口迁移/恢复")
    parser.add_argument("--apply", action="store_true", help="备份并改写 ws_url")
    parser.add_argument("--restore", action="store_true", help="从备份恢复 accounts.json")
    parser.add_argument("--accounts", type=Path, default=REPO_ROOT / "data/pallas_protocol/accounts.json")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env")
    args = parser.parse_args()

    if args.apply == args.restore:
        parser.error("请指定 --apply 或 --restore 之一")

    if args.restore:
        restore_accounts_file(accounts_path=args.accounts, backup_path=args.backup)
        print(f"已恢复 {args.accounts} <- {args.backup}")
        return 0

    summary = sync_accounts_ws_urls(
        args.accounts,
        env_path=args.env,
        backup_path=args.backup,
    )
    print(
        f"已迁移 {summary.changed_count} 个账号 ws_url -> worker 端口"
    )
    print(f"备份: {args.backup}")
    if summary.changed_count:
        print("请在协议端控制台对各账号「重启」或同步 OneBot 配置使 NapCat 生效。")
    else:
        print("（无 ws_url 变更）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
