from __future__ import annotations

import argparse  # noqa: TC003

from pallas.console.cli.deploy_ops import apply_deploy_profile
from pallas.core.foundation.deploy_profile import DEPLOY_PROFILES


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("deploy", help="应用 deploy/ 部署模板")
    deploy_sub = parser.add_subparsers(dest="deploy_command", required=True)
    apply_parser = deploy_sub.add_parser("apply", help="合并模板配置")
    apply_parser.add_argument(
        "profile",
        choices=sorted(DEPLOY_PROFILES.keys()),
        help="部署模板 id",
    )
    apply_parser.add_argument("--dry-run", action="store_true", help="只打印将写入的 env 键")
    apply_parser.set_defaults(handler=run_apply)


def run_apply(args: argparse.Namespace) -> int:
    return apply_deploy_profile(args.profile, dry_run=bool(args.dry_run))
