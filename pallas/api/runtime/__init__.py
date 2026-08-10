"""Stable exact-command registration API for the direct message runtime."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event


@dataclass(frozen=True, slots=True)
class DirectCommandContext:
    bot: Bot
    event: Event
    bot_id: int
    group_id: int
    message_id: int
    command_text: str


@dataclass(frozen=True, slots=True)
class DirectReply:
    message: object


@dataclass(frozen=True, slots=True)
class DirectWorkJob:
    kind: str
    payload: dict[str, Any]
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("work job kind is required")
        if not self.idempotency_key.strip():
            raise ValueError("work job idempotency key is required")
        if not isinstance(self.payload, dict):
            raise ValueError("work job payload must be a dict")
        object.__setattr__(self, "kind", self.kind.strip())
        object.__setattr__(self, "payload", copy.deepcopy(self.payload))
        object.__setattr__(self, "idempotency_key", self.idempotency_key.strip())


@dataclass(frozen=True, slots=True)
class DirectCompletionEffect:
    name: str
    run: Callable[[], Awaitable[None]]
    wait_for_completion: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("completion effect name is required")
        object.__setattr__(self, "name", self.name.strip())


@dataclass(frozen=True, slots=True)
class DirectCommandResult:
    replies: tuple[DirectReply, ...] = ()
    work_jobs: tuple[DirectWorkJob, ...] = ()
    effects: tuple[DirectCompletionEffect, ...] = ()
    fallback_to_matcher: bool = False
    fallback_reason: str | None = None
    continue_matcher: bool = False

    def __post_init__(self) -> None:
        if self.fallback_to_matcher and (self.replies or self.work_jobs or self.effects):
            raise ValueError("matcher fallback cannot contain side effects")
        if self.fallback_reason is not None and not self.fallback_reason.strip():
            raise ValueError("fallback reason cannot be empty")
        if self.fallback_reason and not self.fallback_to_matcher:
            raise ValueError("fallback reason requires matcher fallback")
        if self.continue_matcher and self.fallback_to_matcher:
            raise ValueError("matcher fallback cannot also continue matcher execution")


type DirectCommandCallback = Callable[[DirectCommandContext], Awaitable[DirectCommandResult]]


@dataclass(frozen=True, slots=True)
class ExactCommandDeclaration:
    handler_id: str
    module: str
    commands: frozenset[str]
    command_id: str
    execute: DirectCommandCallback
    continue_matcher: bool = False


_declarations: list[ExactCommandDeclaration] = []


def reply(message: object, *, continue_matcher: bool = False) -> DirectCommandResult:
    return DirectCommandResult(replies=(DirectReply(message),), continue_matcher=continue_matcher)


def completion_effect(name: str, run: Callable[[], Awaitable[None]]) -> DirectCompletionEffect:
    return DirectCompletionEffect(name=name, run=run)


def matcher_fallback(reason: str | None = None) -> DirectCommandResult:
    return DirectCommandResult(fallback_to_matcher=True, fallback_reason=reason)


def register_exact_command_handler(
    *,
    handler_id: str,
    module: str,
    commands: Iterable[str],
    command_id: str,
    execute: DirectCommandCallback,
    continue_matcher: bool = False,
) -> ExactCommandDeclaration:
    normalized_handler_id = handler_id.strip()
    normalized_module = module.strip()
    normalized_command_id = command_id.strip()
    normalized_commands = frozenset(command.strip() for command in commands if command.strip())
    if not normalized_handler_id:
        raise ValueError("handler_id is required")
    if not normalized_module:
        raise ValueError("module is required")
    if not normalized_command_id:
        raise ValueError("command_id is required")
    if not normalized_commands:
        raise ValueError("at least one exact command is required")
    declaration = ExactCommandDeclaration(
        handler_id=normalized_handler_id,
        module=normalized_module,
        commands=normalized_commands,
        command_id=normalized_command_id,
        execute=execute,
        continue_matcher=continue_matcher,
    )
    _declarations.append(declaration)
    return declaration


def exact_command_declarations() -> tuple[ExactCommandDeclaration, ...]:
    return tuple(_declarations)


def remove_exact_command_handlers(module: str) -> None:
    normalized_module = module.strip()
    _declarations[:] = [item for item in _declarations if item.module != normalized_module]


def reset_exact_command_handlers() -> None:
    _declarations.clear()


__all__ = [
    "DirectCommandContext",
    "DirectCommandResult",
    "DirectCompletionEffect",
    "DirectReply",
    "DirectWorkJob",
    "ExactCommandDeclaration",
    "completion_effect",
    "matcher_fallback",
    "register_exact_command_handler",
    "reply",
]
