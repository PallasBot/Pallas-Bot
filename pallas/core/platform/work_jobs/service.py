"""独立 work aux 的启动入口。"""

from __future__ import annotations

import asyncio
import os
import socket
from typing import TYPE_CHECKING

from nonebot import logger

from .runtime import build_work_job_store
from .worker import WorkJobWorker

if TYPE_CHECKING:
    from .worker import WorkJobHandler


async def run_work_service(handlers: dict[str, WorkJobHandler]) -> None:
    from pallas.core.foundation.db import init_db

    await init_db()
    worker = WorkJobWorker(
        store=build_work_job_store(),
        owner=f"{socket.gethostname()}:{os.getpid()}",
        handlers=handlers,
    )
    logger.info("work aux started handlers={}", sorted(handlers))
    while True:
        if not await worker.run_once():
            await asyncio.sleep(0.2)
