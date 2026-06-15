#!/usr/bin/env python3
"""单进程 unified：将全部 enabled 账号 ws_url 对齐同一 HTTP/OneBot 端口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.platform.shard.registry.sync_protocol_ports import restore_accounts_file  # noqa: E402
from src.platform.shard.registry.sync_unified_protocol_ports import (  # noqa: E402
    format_unified_sync_user_message,
    resolve_unified_listen_port,
    sync_accounts_ws_urls_unified,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="unified：同步 accounts.json ws_url 与 instances onebot 配置到单进程端口",
    )
    parser.add_argument(
        "--accounts",
        type=Path,
        default=REPO_ROOT / "data/pallas_protocol/accounts.json",
        help="accounts.json 路径",
    )
    parser.add_argument("--env", type=Path, default=REPO_ROOT / ".env", help="读取 PORT / WS 相关环境变量")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认读 PORT / pallas.toml bootstrap.port）")
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

    env_path = args.env if args.env.is_file() else None
    listen_port = args.port or resolve_unified_listen_port(env_path=env_path)

    try:
        result = sync_accounts_ws_urls_unified(
            args.accounts,
            env_path=env_path,
            backup_path=args.backup,
            dry_run=args.dry_run,
            port=listen_port,
        )
    except (FileNotFoundError, ValueError, OSError) as err:
        print(f"协议端端口同步失败: {err}", file=sys.stderr)
        return 1

    if args.dry_run and (result.changed_count > 0 or result.onebot_drift_count > 0):
        msg = format_unified_sync_user_message(result, backup_path=None)
        msg = msg.replace("已更新", "[dry-run] 将更新")
        msg = msg.replace("已同步", "[dry-run] 将同步")
        msg = msg.replace("已刷新", "[dry-run] 将刷新")
        print(msg)
        return 0

    if result.changed_count == 0 and result.onebot_drift_count == 0:
        if args.verbose:
            print(f"协议端 ws_url 与实例 onebot 均已与 unified 端口 {listen_port} 一致，无需修改。")
        return 0

    if not args.dry_run and (result.changed_count or result.onebot_synced_count):
        print(format_unified_sync_user_message(result, backup_path=args.backup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
