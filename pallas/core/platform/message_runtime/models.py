from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.core.platform.work_jobs.models import WorkJob


class RuntimeMode(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    NATIVE = "native"


@dataclass(frozen=True, slots=True)
class MessageContext:
    ingress_id: str
    bot_id: int
    group_id: int
    message_id: int
    plain_text: str
    raw_text: str
    is_to_me: bool
    command_traffic: bool
    route_modules: frozenset[str]

    def telemetry_fields(self) -> dict[str, str]:
        return {
            "ingress_id": self.ingress_id,
            "bot_id_hash": _telemetry_id_hash(self.bot_id),
            "group_id_hash": _telemetry_id_hash(self.group_id),
        }


@dataclass(frozen=True, slots=True)
class SendAction:
    message: object


@dataclass(frozen=True, slots=True)
class HandlingPlan:
    kind: str
    handler_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in {"native", "legacy"}:
            raise ValueError("plan kind must be native or legacy")
        if not self.reason:
            raise ValueError("plan reason is required")


@dataclass(frozen=True, slots=True)
class HandlingOutcome:
    handled: bool
    actions: tuple[SendAction, ...] = ()
    work_jobs: tuple[WorkJob, ...] = ()
    fallback_to_legacy: bool = False
    continue_legacy: bool = False
    legacy_exclude_modules: frozenset[str] = frozenset()
    error_class: str | None = None

    def __post_init__(self) -> None:
        if self.fallback_to_legacy and (self.actions or self.work_jobs):
            raise ValueError("fallback outcomes cannot contain actions or work jobs")
        if self.error_class and not (self.fallback_to_legacy or self.handled):
            raise ValueError("native errors must either fall back or be committed")
        if self.continue_legacy and (not self.handled or self.fallback_to_legacy):
            raise ValueError("continued legacy execution requires a handled native outcome")


def _telemetry_id_hash(value: int) -> str:
    return hashlib.sha256(f"message-runtime:{value}".encode()).hexdigest()[:16]
