"""Database lifecycle management routes for the WebUI console."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.db.lifecycle_models import LifecyclePolicy
from pallas.core.foundation.db.lifecycle_policy_store import (
    load_lifecycle_policies,
    save_lifecycle_policies,
)
from pallas.core.foundation.db.lifecycle_service import (
    LifecycleConflictError,
    LifecycleService,
)

from .extended_common import check_pallas_write_token

if TYPE_CHECKING:
    from .config import Config


class LifecyclePolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    max_bytes: int | None = Field(default=None, ge=16 * 1024**2, le=2 * 1024**4)

    def to_domain(self) -> LifecyclePolicy:
        return LifecyclePolicy(self.enabled, self.retention_days, self.max_bytes)


class LifecycleObjectModel(BaseModel):
    name: str
    row_count: int | None
    size_bytes: int | None
    dataset_id: str | None
    protected: bool
    protection_reason: str | None
    error: str | None = None


class LifecycleDatasetModel(BaseModel):
    dataset_id: str
    label: str
    risk: Literal["low", "medium", "high"]
    registered_objects: list[str]
    present_objects: list[str]
    row_count: int | None
    size_bytes: int | None
    policy: LifecyclePolicyModel
    supports_retention: bool
    supports_max_bytes: bool
    errors: list[str]


class LifecycleCatalogModel(BaseModel):
    backend: str
    datasets: list[LifecycleDatasetModel]
    unmanaged_objects: list[LifecycleObjectModel]


class LifecycleCatalogResponse(BaseModel):
    ok: bool = True
    data: LifecycleCatalogModel


class LifecyclePoliciesModel(BaseModel):
    policies: dict[str, LifecyclePolicyModel]


class LifecyclePoliciesResponse(BaseModel):
    ok: bool = True
    data: LifecyclePoliciesModel


class LifecyclePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=64)
    policy: LifecyclePolicyModel


class LifecyclePreviewModel(BaseModel):
    dataset_id: str
    candidate_rows: int
    candidate_bytes: int
    confirmation_token: str
    expires_at: float


class LifecyclePreviewResponse(BaseModel):
    ok: bool = True
    data: LifecyclePreviewModel


class LifecycleJobBody(LifecyclePreviewBody):
    confirmation_token: str = Field(min_length=1, max_length=4096)


class LifecycleJobModel(BaseModel):
    job_id: str
    dataset_id: str
    status: Literal["queued", "running", "completed", "failed"]
    deleted_rows: int
    freed_bytes: int
    error: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None


class LifecycleJobResponse(BaseModel):
    ok: bool = True
    data: LifecycleJobModel


_service: LifecycleService | None = None


def get_lifecycle_service() -> LifecycleService:
    global _service
    from pallas.core.foundation.db.runtime import get_db_backend, normalize_db_backend_name

    backend = normalize_db_backend_name(get_db_backend())
    if _service is None or _service.adapter.backend != backend:
        _service = LifecycleService()
    return _service


def register_db_lifecycle_router(router: APIRouter, *, x: str, plugin_config: Config) -> None:
    @router.get(f"{x}/db/lifecycle/catalog", response_model=LifecycleCatalogResponse)
    async def lifecycle_catalog() -> LifecycleCatalogResponse:
        catalog = await get_lifecycle_service().catalog()
        return LifecycleCatalogResponse(data=LifecycleCatalogModel.model_validate(asdict(catalog)))

    @router.get(f"{x}/db/lifecycle/policies", response_model=LifecyclePoliciesResponse)
    async def lifecycle_policies() -> LifecyclePoliciesResponse:
        return policies_response(load_lifecycle_policies())

    @router.put(f"{x}/db/lifecycle/policies", response_model=LifecyclePoliciesResponse)
    async def update_lifecycle_policies(
        body: LifecyclePoliciesModel,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> LifecyclePoliciesResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            policies = save_lifecycle_policies({key: value.to_domain() for key, value in body.policies.items()})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return policies_response(policies)

    @router.post(f"{x}/db/lifecycle/preview", response_model=LifecyclePreviewResponse)
    async def preview_lifecycle_job(
        body: LifecyclePreviewBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> LifecyclePreviewResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            preview = await get_lifecycle_service().preview(body.dataset_id, body.policy.to_domain())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return LifecyclePreviewResponse(data=LifecyclePreviewModel.model_validate(asdict(preview)))

    @router.post(f"{x}/db/lifecycle/jobs", response_model=LifecycleJobResponse)
    async def start_lifecycle_job(
        body: LifecycleJobBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> LifecycleJobResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            job = get_lifecycle_service().start_job(
                body.dataset_id,
                body.policy.to_domain(),
                body.confirmation_token,
            )
        except LifecycleConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return job_response(job)

    @router.get(f"{x}/db/lifecycle/jobs/{{job_id}}", response_model=LifecycleJobResponse)
    async def lifecycle_job(job_id: str) -> LifecycleJobResponse:
        job = get_lifecycle_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="生命周期任务不存在")
        return job_response(job)


def policies_response(policies: dict[str, LifecyclePolicy]) -> LifecyclePoliciesResponse:
    return LifecyclePoliciesResponse(
        data=LifecyclePoliciesModel(
            policies={key: LifecyclePolicyModel.model_validate(asdict(value)) for key, value in policies.items()}
        )
    )


def job_response(job: object) -> LifecycleJobResponse:
    return LifecycleJobResponse(data=LifecycleJobModel.model_validate(asdict(job)))  # type: ignore[arg-type]
