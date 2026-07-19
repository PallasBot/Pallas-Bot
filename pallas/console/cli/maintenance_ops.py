"""组合运维：更新 / 同步 / 重启。"""

from __future__ import annotations

import sys

from pallas.console.cli.sync_ops import run_sync_cli
from pallas.console.cli.update_ops import apply_bot_update


async def run_maintenance(
    *,
    extras: list[str],
    update_bot: bool,
    update_webui: bool,
    restart: bool,
    no_dev: bool = True,
) -> int:
    if extras:
        code = await run_sync_cli(
            extras=extras,
            no_dev=no_dev,
            deploy_full=False,
            deploy_all=False,
        )
        if code != 0:
            return code

    if update_bot:
        from packages.pb_webui.manager import BotGitUpdateError

        try:
            result = await apply_bot_update(restart=False)
        except BotGitUpdateError as e:
            print(e.detail, file=sys.stderr)
            return 1
        print(result.get("message") or f"Bot 已更新至 {result.get('tag', '')}")

    if update_webui:
        from pallas.console.cli.update_ops import WebuiUpdateError, apply_webui_dist_update

        try:
            result = await apply_webui_dist_update(refresh_runtime_meta=False)
        except WebuiUpdateError as e:
            print(e.detail, file=sys.stderr)
            return 1
        print(result.get("message") or f"WebUI 已更新至 {result.get('version', '')}")

    if restart and (update_bot or extras):
        from pallas.console.cli.bot_process import bot_lifecycle_available, run_bot_lifecycle

        if not bot_lifecycle_available():
            print("无法重启：缺少 run_unified_bot.sh 或 run_sharded_bot.sh", file=sys.stderr)
            return 1
        code = run_bot_lifecycle("restart", mode="auto")
        if code != 0:
            return code
        print("Bot 已重启。")

    if extras or update_bot or update_webui:
        print("维护任务完成。")
        return 0

    print("未指定任务：使用 --sync-extra、--update-bot 和/或 --update-webui", file=sys.stderr)
    return 2
