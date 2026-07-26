"""迁移 job 状态机（不连真实库）。"""

from __future__ import annotations

from pallas.core.foundation.db.migrate_jobs import (
    MigrateJobState,
    migrate_job_status_payload,
)


def test_migrate_job_status_payload_shape():
    job = MigrateJobState(job_id="abc", status="queued", phase="queued", dry_run=True)
    payload = migrate_job_status_payload(job)
    assert payload["job_id"] == "abc"
    assert payload["status"] == "queued"
    assert payload["dry_run"] is True
    assert isinstance(payload["logs"], list)
