"""可跨进程传递的后台任务。"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkJob:
    id: str
    kind: str
    payload: dict[str, Any]
    idempotency_key: str
    created_at: float
    attempts: int = 0

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
