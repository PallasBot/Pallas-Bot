"""PostgreSQL 启动期 schema ensure 步骤注册表。"""

from __future__ import annotations

from typing import Any


def list_pg_schema_ensure_steps() -> list[dict[str, str]]:
    from pallas.core.foundation.db.repository_pg import PG_SCHEMA_ENSURE_STEPS

    return [{"id": step_id, "kind": "ddl_ensure"} for step_id, _ in PG_SCHEMA_ENSURE_STEPS]


def run_registered_pg_ensures(connection: Any) -> None:
    from pallas.core.foundation.db.repository_pg import PG_SCHEMA_ENSURE_STEPS
    from pallas.core.foundation.db.schema_observability import run_schema_ensure_step

    for step_id, step_fn in PG_SCHEMA_ENSURE_STEPS:
        run_schema_ensure_step(step_id, step_fn, connection)
