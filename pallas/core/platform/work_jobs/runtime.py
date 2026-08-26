"""按当前数据库后端选择后台任务持久化实现。"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from .store import WorkJobStore


def build_work_job_store(
    *,
    completion_retention: Mapping[str, str] | None = None,
    notify_completed: Callable[[], Awaitable[None]] | None = None,
) -> WorkJobStore:
    from pallas.core.foundation.db import get_db_backend

    backend = str(get_db_backend() or "").strip().lower()
    if backend == "postgresql":
        from .pg_store import PostgresWorkJobStore

        return PostgresWorkJobStore(
            completion_retention=completion_retention,
            notify_completed=notify_completed,
        )
    if backend == "mongodb":
        if notify_completed is not None:
            warnings.warn(
                "notify_completed is only supported by the PostgreSQL work job store; "
                "it is ignored with the MongoDB backend",
                RuntimeWarning,
                stacklevel=2,
            )
        from .mongo_store import MongoWorkJobStore

        return MongoWorkJobStore(completion_retention=completion_retention)
    raise RuntimeError(f"unsupported work job database backend: {backend}")
