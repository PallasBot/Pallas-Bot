from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pallas.core.platform.work_jobs.models import WorkJob


class RuntimeMode(StrEnum):
    MATCHER = "matcher"
    SHADOW = "shadow"
    DIRECT = "direct"

    @classmethod
    def _missing_(cls, value: object) -> RuntimeMode | None:
        return {
            "legacy": cls.MATCHER,
            "native": cls.DIRECT,
        }.get(str(value).strip().lower())


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
            "event_id_hash": _telemetry_text_hash(self.ingress_id),
            "bot_id_hash": _telemetry_id_hash(self.bot_id),
            "group_id_hash": _telemetry_id_hash(self.group_id),
        }


@dataclass(frozen=True, slots=True)
class SendAction:
    message: object


@dataclass(frozen=True, slots=True)
class DeferredAction:
    name: str
    run: Callable[[], Awaitable[None]]
    wait_for_completion: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("deferred action name is required")


@dataclass(frozen=True, slots=True)
class CrossWorkerAction:
    kind: str
    target_bot_id: int
    payload: dict[str, Any]
    idempotency_key: str
    timeout_sec: float = 45.0

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("cross-worker action kind is required")
        if self.target_bot_id <= 0:
            raise ValueError("cross-worker action target bot is required")
        if not self.idempotency_key:
            raise ValueError("cross-worker action idempotency key is required")
        if self.timeout_sec <= 0:
            raise ValueError("cross-worker action timeout must be positive")


@dataclass(frozen=True, slots=True)
class HandlingPlan:
    kind: str
    handler_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.kind not in {"direct", "matcher"}:
            raise ValueError("plan kind must be direct or matcher")
        if not self.reason:
            raise ValueError("plan reason is required")


@dataclass(frozen=True, slots=True)
class HandlingOutcome:
    handled: bool
    handler_id: str | None = None
    actions: tuple[SendAction, ...] = ()
    work_jobs: tuple[WorkJob, ...] = ()
    deferred_actions: tuple[DeferredAction, ...] = ()
    cross_worker_actions: tuple[CrossWorkerAction, ...] = ()
    fallback_to_matcher: bool = False
    fallback_reason: str | None = None
    continue_matcher: bool = False
    matcher_exclude_modules: frozenset[str] = frozenset()
    error_class: str | None = None

    def __post_init__(self) -> None:
        if self.handler_id is not None and not self.handler_id:
            raise ValueError("handler_id cannot be empty")
        if self.fallback_to_matcher and (
            self.actions or self.work_jobs or self.deferred_actions or self.cross_worker_actions
        ):
            raise ValueError("fallback outcomes cannot contain side effects")
        if self.fallback_reason is not None and not self.fallback_reason:
            raise ValueError("fallback reason cannot be empty")
        if self.fallback_reason and not self.fallback_to_matcher:
            raise ValueError("fallback reason requires matcher fallback")
        if self.error_class and not (self.fallback_to_matcher or self.handled):
            raise ValueError("direct errors must either fall back or be committed")
        if self.continue_matcher and (not self.handled or self.fallback_to_matcher):
            raise ValueError("continued matcher execution requires a handled direct outcome")

    @property
    def fallback_to_legacy(self) -> bool:
        return self.fallback_to_matcher

    @property
    def continue_legacy(self) -> bool:
        return self.continue_matcher

    @property
    def legacy_exclude_modules(self) -> frozenset[str]:
        return self.matcher_exclude_modules


def _telemetry_id_hash(value: int) -> str:
    return _telemetry_text_hash(str(value))


def _telemetry_text_hash(value: str) -> str:
    return hashlib.sha256(f"message-runtime:{value}".encode()).hexdigest()[:16]
