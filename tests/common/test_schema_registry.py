"""schema ensure 注册表。"""

from __future__ import annotations

from pallas.core.foundation.db.schema_registry import list_pg_schema_ensure_steps


def test_list_pg_schema_ensure_steps_stable_ids():
    steps = list_pg_schema_ensure_steps()
    assert len(steps) >= 10
    ids = [s["id"] for s in steps]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("ddl.") for i in ids)
    assert "ddl.bot_config_persona" in ids
