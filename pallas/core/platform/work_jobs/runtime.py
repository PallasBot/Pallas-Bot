"""按当前数据库后端选择后台任务持久化实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import WorkJobStore


def build_work_job_store() -> WorkJobStore:
    from pallas.core.foundation.db import get_db_backend

    backend = str(get_db_backend() or "").strip().lower()
    if backend == "postgresql":
        from .pg_store import PostgresWorkJobStore

        return PostgresWorkJobStore()
    if backend == "mongodb":
        from .mongo_store import MongoWorkJobStore

        return MongoWorkJobStore()
    raise RuntimeError(f"unsupported work job database backend: {backend}")
