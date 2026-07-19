from __future__ import annotations

import argparse  # noqa: TC003
import asyncio
import sys


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("update", help="更新本体或 WebUI")
    update_sub = parser.add_subparsers(dest="update_target", required=True)

    bot = update_sub.add_parser("bot", help="git 更新 Bot 仓库")
    bot.add_argument("--restart", action="store_true", help="更新完成后重启 Bot")
    bot.set_defaults(handler=run_bot)

    webui = update_sub.add_parser("webui", help="下载并解压 WebUI dist")
    webui.set_defaults(handler=run_webui)


def run_bot(args: argparse.Namespace) -> int:
    async def work() -> int:
        from packages.pb_webui.manager import BotGitUpdateError
        from pallas.console.cli.update_ops import apply_bot_update

        try:
            data = await apply_bot_update(restart=bool(args.restart))
        except BotGitUpdateError as e:
            print(e.detail, file=sys.stderr)
            return 1
        print(data.get("message") or f"Bot 已更新至 {data.get('tag', '')}")
        return 0

    return asyncio.run(work())


def run_webui(_args: argparse.Namespace) -> int:
    async def work() -> int:
        from pallas.console.cli.update_ops import WebuiUpdateError, apply_webui_dist_update

        try:
            data = await apply_webui_dist_update(refresh_runtime_meta=False)
        except WebuiUpdateError as e:
            print(e.detail, file=sys.stderr)
            return 1
        print(data.get("message") or f"WebUI 已更新至 {data.get('version', '')}")
        return 0

    return asyncio.run(work())
