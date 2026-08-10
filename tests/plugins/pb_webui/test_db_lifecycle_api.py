from dataclasses import replace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from packages.pb_webui import db_lifecycle_api
from packages.pb_webui.config import Config
from pallas.core.foundation.db.lifecycle_models import (
    LifecycleCatalog,
    LifecycleDatasetCatalogItem,
    LifecycleJob,
    LifecyclePolicy,
    LifecyclePreview,
)


class FakeService:
    def __init__(self) -> None:
        self.policy = LifecyclePolicy(True, 30, 1024**3)
        self.job = LifecycleJob("job-1", "message_history", created_at=1)

    async def catalog(self) -> LifecycleCatalog:
        return LifecycleCatalog(
            backend="postgresql",
            datasets=(
                LifecycleDatasetCatalogItem(
                    "message_history",
                    "消息历史",
                    "high",
                    ("message",),
                    ("message",),
                    10,
                    1000,
                    self.policy,
                    True,
                    True,
                ),
            ),
            unmanaged_objects=(),
        )

    async def preview(self, dataset_id: str, policy: LifecyclePolicy) -> LifecyclePreview:
        return LifecyclePreview(dataset_id, 3, 300, "signed", 9999999999)

    def start_job(self, dataset_id: str, policy: LifecyclePolicy, token: str) -> LifecycleJob:
        assert token == "signed"
        self.job = replace(self.job, dataset_id=dataset_id)
        return self.job

    def get_job(self, job_id: str) -> LifecycleJob | None:
        return self.job if job_id == self.job.job_id else None


def build_app(monkeypatch) -> tuple[FastAPI, FakeService, list[bool]]:
    service = FakeService()
    auth_checks: list[bool] = []
    monkeypatch.setattr(db_lifecycle_api, "get_lifecycle_service", lambda: service)
    monkeypatch.setattr(db_lifecycle_api, "check_pallas_write_token", lambda *args, **kwargs: auth_checks.append(True))
    monkeypatch.setattr(db_lifecycle_api, "load_lifecycle_policies", lambda: {"message_history": service.policy})
    monkeypatch.setattr(
        db_lifecycle_api,
        "save_lifecycle_policies",
        lambda policies: policies,
    )
    app = FastAPI()
    db_lifecycle_api.register_db_lifecycle_router(app, x="/pallas/api", plugin_config=Config())
    return app, service, auth_checks


@pytest.mark.asyncio
async def test_catalog_and_policies_contract(monkeypatch) -> None:
    app, _service, auth_checks = build_app(monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        catalog = await client.get("/pallas/api/db/lifecycle/catalog")
        policies = await client.get("/pallas/api/db/lifecycle/policies")
        saved = await client.put(
            "/pallas/api/db/lifecycle/policies",
            json={"policies": {"message_history": {"enabled": True, "retention_days": 60, "max_bytes": None}}},
        )

    assert catalog.status_code == 200
    assert catalog.json()["data"]["datasets"][0]["dataset_id"] == "message_history"
    assert policies.status_code == 200
    assert saved.status_code == 200
    assert auth_checks == [True]


@pytest.mark.asyncio
async def test_preview_and_job_contract(monkeypatch) -> None:
    app, _service, auth_checks = build_app(monkeypatch)
    policy = {"enabled": True, "retention_days": 30, "max_bytes": 1024**3}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        preview = await client.post(
            "/pallas/api/db/lifecycle/preview",
            json={"dataset_id": "message_history", "policy": policy},
        )
        started = await client.post(
            "/pallas/api/db/lifecycle/jobs",
            json={"dataset_id": "message_history", "policy": policy, "confirmation_token": "signed"},
        )
        job = await client.get("/pallas/api/db/lifecycle/jobs/job-1")
        missing = await client.get("/pallas/api/db/lifecycle/jobs/missing")

    assert preview.json()["data"]["candidate_rows"] == 3
    assert started.status_code == 200
    assert job.status_code == 200
    assert missing.status_code == 404
    assert auth_checks == [True, True]
