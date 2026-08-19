"""发送任务消费：持有目标 bot 的消息进程领取 DB outbox 中的 bot action 并本地执行。

与协调 Redis 解耦：work aux 的 result action 落成 ``bot_action.send`` 任务，
由持有 bot 的进程轮询领取后经 ``_execute_local`` 发送，单机无 Redis 部署同样可用。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .result_committer import SEND_JOB_KIND

if TYPE_CHECKING:
    from pallas.api.runtime import DirectWorkResult


async def handle_bot_action_send(payload: dict) -> DirectWorkResult | None:
    from pallas.core.platform.shard.coord.bot_action import _execute_local

    action = str(payload.get("action") or "")
    try:
        bot_qq = int(payload.get("bot_qq") or 0)
    except (TypeError, ValueError):
        bot_qq = 0
    action_payload = payload.get("payload")
    if not action or bot_qq <= 0 or not isinstance(action_payload, dict):
        return None
    await _execute_local(action, bot_qq, action_payload)
    return None


_started = False


def start_bot_action_send_consumer() -> None:
    """持有 bot 的消息进程启动一个发送任务 consumer。"""
    global _started
    if _started:
        return
    _started = True
    asyncio.create_task(_run_send_consumer_loop(), name="bot_action_send_consumer")


async def _run_send_consumer_loop() -> None:
    from pallas.core.platform.work_jobs.runtime import build_work_job_store
    from pallas.core.platform.work_jobs.service import run_work_consumer
    from pallas.core.platform.work_jobs.worker import WorkJobWorker

    store = build_work_job_store()
    worker = WorkJobWorker(
        store=store,
        owner="bot_action_send",
        handlers={SEND_JOB_KIND: handle_bot_action_send},
        kinds=frozenset({SEND_JOB_KIND}),
        batch_size=4,
    )
    await run_work_consumer(worker)
