"""后台任务辅助进程入口。"""

from __future__ import annotations

import asyncio

import nonebot

from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
from pallas.core.platform.work_jobs.service import run_work_service


def repeater_work_handlers():
    from packages.repeater.work_handler import repeater_work_handlers as build_handlers

    return build_handlers()


def load_work_handlers():
    nonebot.init()
    return repeater_work_handlers()


def main() -> None:
    apply_repo_settings_to_environ()
    asyncio.run(run_work_service(load_work_handlers()))


if __name__ == "__main__":
    main()
