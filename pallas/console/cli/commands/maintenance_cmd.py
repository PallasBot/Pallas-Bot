from __future__ import annotations

import argparse  # noqa: TC003
import asyncio


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("maintenance", help="组合运维（同步 / 更新 / 重启）")
    maint_sub = parser.add_subparsers(dest="maintenance_command", required=True)
    run_parser = maint_sub.add_parser("run", help="执行维护任务")
    run_parser.add_argument(
        "--sync-extra",
        action="append",
        default=[],
        metavar="NAME",
        help="维护前 uv sync --extra，可重复",
    )
    run_parser.add_argument("--update-bot", action="store_true", help="git 更新 Bot 本体")
    run_parser.add_argument("--update-webui", action="store_true", help="下载并解压 WebUI dist")
    run_parser.add_argument(
        "--restart",
        action="store_true",
        help="Bot 更新后重启（默认与 --update-bot 同开）",
    )
    run_parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Bot 更新后不重启",
    )
    run_parser.add_argument("--dev", action="store_true", help="sync 时包含 dev 依赖")
    run_parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    from pallas.console.cli.maintenance_ops import run_maintenance

    update_bot = bool(args.update_bot)
    update_webui = bool(args.update_webui)
    restart = bool(args.restart) or (update_bot and not args.no_restart)

    return asyncio.run(
        run_maintenance(
            extras=list(args.sync_extra or []),
            update_bot=update_bot,
            update_webui=update_webui,
            restart=restart,
            no_dev=not args.dev,
        ),
    )
