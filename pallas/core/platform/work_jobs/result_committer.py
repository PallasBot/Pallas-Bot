"""提交 durable work handler 返回的结构化 Bot 动作。

work aux 不持有 bot 连接，无法直接发送；这里把 result action 转成 DB outbox 里的
发送任务（``bot_action.send``），由持有目标 bot 的消息进程领取并本地执行。这样确认
回复不依赖协调 Redis，单机无 Redis 部署同样可用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

from .models import WorkJob

if TYPE_CHECKING:
    from pallas.api.runtime import DirectWorkResult

    from .store import WorkJobStore

SEND_JOB_KIND = "bot_action.send"


class WorkResultCommitError(RuntimeError):
    committed = True


class WorkResultCommitter:
    def __init__(self, *, store: WorkJobStore) -> None:
        self._store = store

    async def commit(
        self,
        result: DirectWorkResult,
        *,
        job_kind: str = "",
        job_id: str = "",
    ) -> bool:
        if not result.actions:
            return False
        jobs: list[WorkJob] = []
        for action in result.actions:
            try:
                action.validate()
            except ValueError as exc:
                logger.warning(
                    "work aux: result action [{}] for bot [{}] is invalid while committing job [{}] of kind [{}]: {}",
                    action.action,
                    action.target_bot_id,
                    job_id,
                    job_kind,
                    exc,
                )
                raise WorkResultCommitError(str(exc)) from exc
            jobs.append(
                WorkJob.create(
                    kind=SEND_JOB_KIND,
                    payload={
                        "action": action.action,
                        "bot_qq": action.target_bot_id,
                        "payload": dict(action.payload),
                        "timeout_sec": action.timeout_sec,
                    },
                    idempotency_key=f"send:{job_kind}:{job_id}:{action.action}:{action.target_bot_id}",
                )
            )
        await self._store.enqueue_many(jobs)
        return True
