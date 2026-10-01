"""可跨进程传递的后台任务。"""

from __future__ import annotations

import copy
import math
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any


class InvalidWorkJobPayloadError(ValueError):
    """Payload cannot be represented without losing data in PostgreSQL JSONB."""


def normalize_work_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove PostgreSQL-forbidden NULs without mutating the submitted payload."""
    if not isinstance(payload, dict):
        raise InvalidWorkJobPayloadError("work job payload must be a dict")

    def normalize(value: Any, parents: set[int]) -> Any:
        if isinstance(value, str):
            return value.replace("\x00", "")
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidWorkJobPayloadError("work job payload contains a non-finite number")
            return value
        if isinstance(value, dict):
            container = value.items()
        elif isinstance(value, (list, tuple)):
            container = value
        else:
            raise InvalidWorkJobPayloadError("work job payload contains a non-JSON value")

        identity = id(value)
        if identity in parents:
            raise InvalidWorkJobPayloadError("work job payload contains a circular reference")
        parents.add(identity)
        try:
            if isinstance(value, dict):
                result = {}
                for key, child in container:
                    if not isinstance(key, str):
                        raise InvalidWorkJobPayloadError("work job payload keys must be strings")
                    normalized_key = key.replace("\x00", "")
                    if normalized_key in result:
                        raise InvalidWorkJobPayloadError("work job payload keys collide after NUL normalization")
                    result[normalized_key] = normalize(child, parents)
                return result
            normalized = [normalize(item, parents) for item in container]
            return tuple(normalized) if isinstance(value, tuple) else normalized
        finally:
            parents.remove(identity)

    return normalize(payload, set())


@dataclass(frozen=True, slots=True)
class WorkJob:
    id: str
    kind: str
    payload: dict[str, Any]
    idempotency_key: str
    created_at: float
    attempts: int = 0
    lease_id: str | None = None

    @classmethod
    def create(cls, *, kind: str, payload: dict[str, Any], idempotency_key: str) -> WorkJob:
        normalized_kind = str(kind or "").strip()
        if not normalized_kind:
            raise ValueError("work job kind is required")
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key:
            raise ValueError("work job idempotency key is required")
        if not isinstance(payload, dict):
            raise ValueError("work job payload must be a dict")
        return cls(
            id=uuid.uuid4().hex,
            kind=normalized_kind,
            payload=copy.deepcopy(payload),
            idempotency_key=normalized_key,
            created_at=time.time(),
        )


def normalize_work_job_batch(jobs: list[WorkJob]) -> tuple[list[WorkJob], int]:
    normalized = []
    invalid_count = 0
    for job in jobs:
        try:
            payload = normalize_work_job_payload(job.payload)
        except InvalidWorkJobPayloadError:
            invalid_count += 1
        else:
            normalized.append(replace(job, payload=payload))
    return normalized, invalid_count
