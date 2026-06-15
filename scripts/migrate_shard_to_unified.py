#!/usr/bin/env python3
"""分片 → 单进程 unified：停分片、改配置、同步协议端 ws_url。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STATE_DIR = REPO_ROOT / ".unified_test_state"
ACCOUNTS_PATH = REPO_ROOT / "data/pallas_protocol/accounts.json"
WEBUI_PATH = REPO_ROOT / "data/pallas_config/webui.json"
PALLAS_TOML = REPO_ROOT / "config/pallas.toml"
SHARD_SCRIPT = REPO_ROOT / "scripts/run_sharded_bot.sh"


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_file(path: Path, dest_dir: Path) -> Path | None:
    if not path.is_file():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{path.name}.{stamp()}.bak"
    shutil.copy2(path, target)
    return target


def set_shard_enabled(enabled: bool) -> None:
    value = "true" if enabled else "false"
    if PALLAS_TOML.is_file():
        text = PALLAS_TOML.read_text(encoding="utf-8")
        if "PALLAS_SHARD_ENABLED" in text:
            import re

            text = re.sub(
                r'(PALLAS_SHARD_ENABLED\s*=\s*)"?(?:true|false)"?',
                rf'\1"{value}"',
                text,
                count=1,
            )
        else:
            text = text.rstrip() + f'\nPALLAS_SHARD_ENABLED = "{value}"\n'
        PALLAS_TOML.write_text(text, encoding="utf-8")

    if WEBUI_PATH.is_file():
        data = json.loads(WEBUI_PATH.read_text(encoding="utf-8"))
        env = data.get("env")
        if isinstance(env, dict):
            env["PALLAS_SHARD_ENABLED"] = value
        sections = data.get("sections")
        if isinstance(sections, dict):
            for section in sections.values():
                if isinstance(section, dict) and "PALLAS_SHARD_ENABLED" in section:
                    section["PALLAS_SHARD_ENABLED"] = value
        WEBUI_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stop_sharded_if_running() -> None:
    if not SHARD_SCRIPT.is_file():
        return
    subprocess.run([str(SHARD_SCRIPT), "stop"], cwd=REPO_ROOT, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只预览 ws_url 变更，不写盘")
    parser.add_argument("--skip-stop", action="store_true", help="不执行 run_sharded_bot.sh stop")
    parser.add_argument("--skip-config", action="store_true", help="不改 pallas.toml / webui.json")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="单进程监听端口（默认读 PORT / pallas.toml bootstrap.port）",
    )
    args = parser.parse_args()

    from src.platform.shard.registry.sync_unified_protocol_ports import (
        format_unified_sync_user_message,
        resolve_unified_listen_port,
        sync_accounts_ws_urls_unified,
    )

    listen_port = args.port or resolve_unified_listen_port(env_path=REPO_ROOT / ".env")
    backup_dir = STATE_DIR / f"pre_unified_{stamp()}"
    backup_file(ACCOUNTS_PATH, backup_dir)
    backup_file(PALLAS_TOML, backup_dir)
    backup_file(WEBUI_PATH, backup_dir)
    if (REPO_ROOT / "data/pallas_shard/registry.json").is_file():
        backup_file(REPO_ROOT / "data/pallas_shard/registry.json", backup_dir)

    print(f"单进程目标端口: {listen_port}")
    print(f"备份目录: {backup_dir}")

    if not args.skip_stop and not args.dry_run:
        print("停止分片进程…")
        stop_sharded_if_running()

    if not args.skip_config and not args.dry_run:
        print("写入 PALLAS_SHARD_ENABLED=false …")
        set_shard_enabled(False)

    if not ACCOUNTS_PATH.is_file():
        print(f"未找到 {ACCOUNTS_PATH}，跳过协议端同步", file=sys.stderr)
        return 1

    backup_accounts = backup_dir / "accounts.json.pre_sync.bak"
    result = sync_accounts_ws_urls_unified(
        ACCOUNTS_PATH,
        env_path=REPO_ROOT / ".env",
        backup_path=None if args.dry_run else backup_accounts,
        dry_run=args.dry_run,
        port=listen_port,
    )
    print(format_unified_sync_user_message(result, backup_path=backup_accounts if not args.dry_run else None))

    if args.dry_run:
        print("\n[dry-run] 未改配置、未停进程。确认后去掉 --dry-run 再执行。")
        return 0

    print("\n下一步:")
    print("  1. 在协议端控制台对变更账号执行「重启」")
    print("  2. ./scripts/run_unified_bot.sh start")
    print("  3. 观察 WebUI / 日志；测完可 ./scripts/migrate_unified_to_shard.py 回分片")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
