"""从 ArknightsGameData 拉取 character/skill 表，生成决斗用六星 JSON 与本地头像到 resource/arknights/。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.arknights.duel_sync import (  # noqa: E402
    OPERATORS_JSON,
    operator_ids_from_payload,
    sync_avatars_sync,
    sync_operators_json_sync,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步决斗六星干员表与头像到 resource/arknights/")
    parser.add_argument(
        "--no-avatars",
        action="store_true",
        help="仅更新 operators_6star.json，不下载 PNG 头像",
    )
    parser.add_argument(
        "--avatars-only",
        action="store_true",
        help="仅补全缺失头像（不重新拉 character/skill 表）",
    )
    args = parser.parse_args()

    if args.avatars_only:
        from src.common.arknights.duel_sync import load_operators_payload

        payload = load_operators_payload()
        if not payload:
            print(f"missing {OPERATORS_JSON}, run without --avatars-only first")
            return 1
        ids = operator_ids_from_payload(payload)
    else:
        print("fetching character_table + skill_table ...")
        payload = sync_operators_json_sync()
        print(f"wrote {OPERATORS_JSON} ({payload.get('count', 0)} operators)")
        ids = operator_ids_from_payload(payload)

    if args.no_avatars:
        return 0

    print(f"syncing avatars ({len(ids)} operators) ...")
    ok, tried = sync_avatars_sync(ids, missing_only=True)
    print(f"avatars: ok={ok} tried={tried}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
