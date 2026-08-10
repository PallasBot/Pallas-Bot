"""Database lifecycle domain values shared by console backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LifecycleRisk = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    enabled: bool
    retention_days: int | None
    max_bytes: int | None


@dataclass(frozen=True, slots=True)
class LifecycleDatasetDefinition:
    dataset_id: str
    label: str
    objects: tuple[str, ...]
    risk: LifecycleRisk
    default_policy: LifecyclePolicy
    supports_retention: bool = True
    supports_max_bytes: bool = True


@dataclass(frozen=True, slots=True)
class LifecycleObjectClassification:
    object_name: str
    dataset_id: str | None
    protected: bool
    protection_reason: str | None


@dataclass(frozen=True, slots=True)
class LifecycleObjectStat:
    name: str
    row_count: int | None
    size_bytes: int | None
    dataset_id: str | None
    protected: bool
    protection_reason: str | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleDatasetCatalogItem:
    dataset_id: str
    label: str
    risk: LifecycleRisk
    registered_objects: tuple[str, ...]
    present_objects: tuple[str, ...]
    row_count: int | None
    size_bytes: int | None
    policy: LifecyclePolicy
    supports_retention: bool = True
    supports_max_bytes: bool = True
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LifecycleCatalog:
    backend: str
    datasets: tuple[LifecycleDatasetCatalogItem, ...]
    unmanaged_objects: tuple[LifecycleObjectStat, ...]


@dataclass(frozen=True, slots=True)
class LifecyclePreview:
    dataset_id: str
    candidate_rows: int
    candidate_bytes: int
    confirmation_token: str
    expires_at: float


@dataclass(slots=True)
class LifecycleJob:
    job_id: str
    dataset_id: str
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    deleted_rows: int = 0
    freed_bytes: int = 0
    error: str | None = None
    created_at: float = 0
    started_at: float | None = None
    finished_at: float | None = None
