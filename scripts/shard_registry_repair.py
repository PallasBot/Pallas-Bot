#!/usr/bin/env python3
"""修复膨胀的 registry.json：从 .env 同步顶层参数、裁剪空分片、恢复生产归属。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.platform.shard.registry.config import get_shard_registry_settings  # noqa: E402
from src.platform.shard.registry.store import (  # noqa: E402
    ShardRegistry,
    apply_registry_settings_from_env,
    clear_shard_registry_cache,
    ensure_test_shard_row,
    get_shard_registry,
    get_test_config,
    get_test_shard_id,
    save_shard_registry,
)

# 生产环境基线归属
PRODUCTION_ASSIGNMENTS: dict[str, int] = {
    "2868075548": 0,
    "3328656396": 0,
    "3599334092": 0,
    "2324805745": 0,
    "913934574": 0,
    "3032874010": 1,
    "3831667476": 1,
    "1823196773": 1,
    "2387466426": 1,
    "3887247010": 1,
    "3037607806": 2,
    "1119799855": 2,
    "923722427": 2,
    "2995241261": 2,
    "3821083709": 2,
    "3934905725": 3,
    "3234802804": 3,
    "1745530086": 3,
    "3879348674": 3,
    "320004531": 3,
    "1354970010": 4,
    "1591609510": 4,
    "3118569874": 4,
    "3976691212": 4,
    "3962466422": 4,
    "2927116873": 5,
    "3988307357": 5,
    "3907360849": 5,
    "3944700196": 5,
    "2136204582": 5,
    "2955878537": 6,
    "3803448823": 6,
    "3458296165": 6,
}


def backup_registry(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = path.parent / f"registry.json.bak.{stamp}"
    shutil.copy2(path, dest)
    return dest


def cmd_compact(_args: argparse.Namespace) -> int:
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()
    path = REPO_ROOT / "data/pallas_shard/registry.json"
    if path.is_file():
        bak = backup_registry(path)
        print(f"已备份: {bak}")
    reg = get_shard_registry()
    before = len(reg.shards)
    save_shard_registry(reg)
    reg = get_shard_registry()
    print(
        json.dumps(
            {
                "ok": True,
                "shards_before": before,
                "shards_after": len(reg.shards),
                "bots_per_shard": reg.bots_per_shard,
                "worker_base_port": reg.worker_base_port,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_restore_production(args: argparse.Namespace) -> int:
    clear_shard_registry_cache()
    get_shard_registry_settings.cache_clear()
    path = REPO_ROOT / "data/pallas_shard/registry.json"
    if path.is_file() and not args.no_backup:
        bak = backup_registry(path)
        print(f"已备份: {bak}")

    if path.is_file():
        reg = ShardRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))
    else:
        reg = ShardRegistry()
    apply_registry_settings_from_env(reg)

    test_cfg = get_test_config(reg)
    test_bots: list[str] = []
    if test_cfg.enabled:
        test_sid = get_test_shard_id(reg)
        test_bots = [k for k, v in reg.assignments.items() if int(v) == test_sid]
        if not test_bots and args.keep_test_bots:
            test_bots = list(args.keep_test_bots)

    reg.assignments = dict(PRODUCTION_ASSIGNMENTS)
    for qq in test_bots:
        reg.assignments[str(qq)] = get_test_shard_id(reg)

    if test_cfg.enabled:
        reg.test = test_cfg
        ensure_test_shard_row(reg)

    save_shard_registry(reg)
    reg = get_shard_registry()
    normal = [s for s in reg.shards if (s.role or "normal") != "test"]
    print(
        json.dumps(
            {
                "ok": True,
                "assignments": len(reg.assignments),
                "normal_shards": len(normal),
                "test": reg.test.model_dump(mode="json") if reg.test else None,
                "bots_per_shard": reg.bots_per_shard,
                "worker_base_port": reg.worker_base_port,
                "message": "已恢复生产归属；请执行 sync_shard_protocol_ports 并重启协议端账号",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="修复分片 registry.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("compact", help="从 .env 同步顶层参数并裁剪空分片").set_defaults(func=cmd_compact)
    p_restore = sub.add_parser(
        "restore-production",
        help="恢复生产 assignments 基线，保留当前 test 分片上的 QQ",
    )
    p_restore.add_argument("--no-backup", action="store_true")
    p_restore.add_argument(
        "--keep-test-bots",
        nargs="*",
        default=["2387466426", "3879348674"],
        help="test 分片为空时默认保留的 QQ",
    )
    p_restore.set_defaults(func=cmd_restore_production)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
