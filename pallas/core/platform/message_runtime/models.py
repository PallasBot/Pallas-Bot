from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum


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
    message: str


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
    fallback_to_legacy: bool = False

    def __post_init__(self) -> None:
        if self.fallback_to_legacy and self.actions:
            raise ValueError("fallback outcomes cannot contain actions")


def _telemetry_id_hash(value: int) -> str:
    return hashlib.sha256(f"message-runtime:{value}".encode()).hexdigest()[:16]
