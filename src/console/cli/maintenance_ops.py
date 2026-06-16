"""组合运维：更新 / 同步 / 重启。"""

from __future__ import annotations

import sys

from src.console.cli.sync_ops import run_sync_cli
from src.console.cli.update_ops import apply_bot_update


async def run_maintenance(
    *,
    extras: list[str],
    update_bot: bool,
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
        from src.plugins.pallas_webui.manager import BotGitUpdateError

        try:
            result = await apply_bot_update(restart=restart)
        except BotGitUpdateError as e:
            print(e.detail, file=sys.stderr)
            return 1
        print(result.get("message") or f"Bot 已更新至 {result.get('tag', '')}")
        return 0

    if extras:
        print("维护任务完成（仅同步依赖）。")
        return 0

    print("未指定任务：使用 --sync-extra 和/或 --update-bot", file=sys.stderr)
    return 2
