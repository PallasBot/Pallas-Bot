#!/usr/bin/env python3
"""测试分片 worker：注册表 init / 手动迁入迁出 / 协议端 ws 同步。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.shard.registry.config import get_shard_registry_settings  # noqa: E402
from pallas.core.platform.shard.registry.store import (  # noqa: E402
    assign_bot_to_test_shard,
    clear_shard_registry_cache,
    get_shard_registry,
    get_test_config,
    get_test_shard_id,
    init_test_shard,
    list_test_shard_bots,
    remove_bot_from_test_shard,
    resolve_test_port,
)
from pallas.core.platform.shard.registry.sync_protocol_ports import (  # noqa: E402
    apply_env_for_shard_sync,
    format_sync_user_message,
    read_dotenv,
    sync_accounts_ws_urls,
)


def _apply_env(env_path: Path | None) -> None:
    if env_path is None or not env_path.is_file():
        return
    apply_env_for_shard_sync(read_dotenv(env_path))
    get_shard_registry_settings.cache_clear()
    clear_shard_registry_cache()


def cmd_init(args: argparse.Namespace) -> int:
    _apply_env(args.env)
    tc = init_test_shard(port=args.port or 0, shard_id=args.shard_id)
    port = resolve_test_port(get_shard_registry())
    print(
        json.dumps(
            {
                "ok": True,
                "enabled": tc.enabled,
                "shard_id": tc.shard_id,
                "port": port,
                "message": f"测试分片已启用：worker-test（PALLAS_SHARD_ID={tc.shard_id}，WS 端口 {port}）",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    _apply_env(args.env)
    qq = str(args.qq).strip()
    sid = assign_bot_to_test_shard(qq)
    port = resolve_test_port(get_shard_registry())
    msg = {"ok": True, "qq": qq, "shard_id": sid, "port": port}
    if args.sync_ws and args.accounts.is_file():
        result = sync_accounts_ws_urls(
            args.accounts,
            env_path=args.env,
            backup_path=args.backup,
            dry_run=False,
        )
        msg["ws_sync"] = result.changed_count
        if result.changed_count:
            print(format_sync_user_message(result, backup_path=args.backup), file=sys.stderr)
    print(json.dumps(msg, ensure_ascii=False, indent=2))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    _apply_env(args.env)
    qq = str(args.qq).strip()
    if not remove_bot_from_test_shard(qq):
        print(json.dumps({"ok": False, "error": f"账号 {qq} 不在测试分片"}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "qq": qq, "removed": True}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    reg = get_shard_registry()
    tc = get_test_config(reg)
    bots = list_test_shard_bots(registry=reg)
    print(
        json.dumps(
            {
                "ok": True,
                "enabled": tc.enabled,
                "shard_id": get_test_shard_id(reg),
                "port": resolve_test_port(reg) if tc.enabled else tc.port,
                "bots": bots,
                "count": len(bots),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    _apply_env(args.env)
    if not args.accounts.is_file():
        print(json.dumps({"ok": False, "error": f"未找到 {args.accounts}"}, ensure_ascii=False))
        return 1
    bots = set(list_test_shard_bots())
    if args.qq:
        bots = {str(args.qq).strip()} & bots
    if not bots:
        print(json.dumps({"ok": True, "changed": 0, "message": "测试分片无账号需同步"}, ensure_ascii=False))
        return 0
    result = sync_accounts_ws_urls(
        args.accounts,
        env_path=args.env,
        backup_path=args.backup,
        dry_run=args.dry_run,
    )
    filtered = [d for d in result.details if str(d.get("qq", "")) in bots]
    result.changed_count = len(filtered)
    result.details = filtered
    if not args.dry_run and result.changed_count:
        print(format_sync_user_message(result, backup_path=args.backup), file=sys.stderr)
    print(
        json.dumps(
            {"ok": True, "changed": result.changed_count, "details": filtered, "dry_run": args.dry_run},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pallas 分片测试 worker 注册表管理")
    parser.add_argument(
        "--env",
        type=Path,
        default=REPO_ROOT / ".env",
        help="用于读取 PALLAS_SHARD_* 的 .env",
    )
    parser.add_argument(
        "--accounts",
        type=Path,
        default=REPO_ROOT / "data/pallas_protocol/accounts.json",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        default=REPO_ROOT / "data/pallas_shard/run/accounts.json.test_sync",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="启用 registry.test 并写入测试分片端口")
    p_init.add_argument("--port", type=int, default=0, help="测试 worker 端口，0=自动")
    p_init.add_argument("--shard-id", type=int, default=None, help="测试分片编号，默认 99")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="手动将 QQ 迁入测试分片")
    p_add.add_argument("qq", help="牛牛 QQ 号")
    p_add.add_argument("--sync-ws", action="store_true", help="同步该账号 accounts.json ws_url")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="从测试分片移除 QQ（不删除协议端账号）")
    p_remove.add_argument("qq")
    p_remove.set_defaults(func=cmd_remove)

    p_list = sub.add_parser("list", help="列出测试分片上的 QQ")
    p_list.set_defaults(func=cmd_list)

    p_sync = sub.add_parser("sync-ws", help="仅同步测试分片账号的 ws_url")
    p_sync.add_argument("--qq", default="", help="只同步指定 QQ")
    p_sync.add_argument("--dry-run", action="store_true")
    p_sync.set_defaults(func=cmd_sync)

    args = parser.parse_args()
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
