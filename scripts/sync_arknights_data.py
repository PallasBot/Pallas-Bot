"""从 ArknightsGameData 同步 resource/arknights/ 数据（决斗与知识库共用）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pallas.core.domain.arknights.sync import (  # noqa: E402
    ArknightsSyncPlan,
    duel_sync_plan,
    full_sync_plan,
    kb_sync_plan,
    run_arknights_sync,
)


def build_plan(args: argparse.Namespace) -> ArknightsSyncPlan:
    if args.all:
        return full_sync_plan()
    if args.kb:
        return kb_sync_plan(avatars=not args.no_avatars)

    plan = duel_sync_plan(avatars=not args.no_avatars, avatars_only=args.avatars_only)
    if args.skip_operators:
        plan.operators = False
    plan.handbook_enrich = args.handbook
    plan.enemies = args.enemies
    plan.maintainer_lore = args.maintainer_lore
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同步方舟数据到 resource/arknights/（决斗六星表、头像、档案摘录、敌人图鉴）",
    )
    parser.add_argument("--all", action="store_true", help="operators + avatars + handbook + enemies + maintainer lore")
    parser.add_argument("--kb", action="store_true", help="知识库预设：全星级 operators.json + 六星表 + 档案 + 敌人")
    parser.add_argument("--handbook", action="store_true", help="六星干员 JSON 合并档案摘录 handbook_lines")
    parser.add_argument("--enemies", action="store_true", help="写入 enemies_handbook.json")
    parser.add_argument(
        "--maintainer-lore",
        action="store_true",
        help="写入 .cache/duel_ark_lore/（决斗事件撰写参考，已 gitignore）",
    )
    parser.add_argument("--no-avatars", action="store_true", help="不下载 PNG 头像")
    parser.add_argument("--skip-operators", action="store_true", help="不写入 operators_6star.json")
    args = parser.parse_args()

    plan = build_plan(args)
    result = run_arknights_sync(plan)
    for line in result.messages:
        print(line)
    if plan.avatars_only and result.operators_count == 0 and not result.operators_path:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
