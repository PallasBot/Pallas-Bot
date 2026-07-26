"""迁移 job 状态机（不连真实库）。"""

from __future__ import annotations

import sys

from pallas.core.foundation.db.migrate_jobs import (
    MigrateJobState,
    _load_migrate_module,
    migrate_job_status_payload,
)


def test_migrate_job_status_payload_shape():
    job = MigrateJobState(job_id="abc", status="queued", phase="queued", dry_run=True)
    payload = migrate_job_status_payload(job)
    assert payload["job_id"] == "abc"
    assert payload["status"] == "queued"
    assert payload["dry_run"] is True
    assert isinstance(payload["logs"], list)


def test_load_migrate_module_registers_sys_modules():
    sys.modules.pop("pallas_migrate_mongo_to_pg", None)
    mod = _load_migrate_module()
    assert mod is sys.modules["pallas_migrate_mongo_to_pg"]
    assert hasattr(mod, "_TableStats")
    assert _load_migrate_module() is mod
