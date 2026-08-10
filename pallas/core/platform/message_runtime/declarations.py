from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.api.perm import satisfies_command_permission
from pallas.api.runtime import (
    DirectCommandContext,
    ExactCommandDeclaration,
    command_declarations,
)
from pallas.core.platform.work_jobs.models import WorkJob

from .models import DeferredAction, HandlingOutcome, MessageContext, SendAction

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

    from pallas.api.runtime import CommandDeclaration


@dataclass(frozen=True, slots=True)
class DeclarationDiagnostic:
    code: str
    handler_id: str
    module: str
    commands: tuple[str, ...]


class DeclaredCommandRuntimeHandler:
    passive = False
    fallback_on_error = False

    def __init__(self, declaration: CommandDeclaration) -> None:
        self._declaration = declaration
        self.handler_id = declaration.handler_id
        self.modules = frozenset({declaration.module})

    def accepts(self, context: MessageContext) -> bool:
        command_text = context.plain_text.strip()
        if isinstance(self._declaration, ExactCommandDeclaration):
            return command_text in self._declaration.commands
        return any(command_text.startswith(prefix) for prefix in self._declaration.prefixes)

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        if not await satisfies_command_permission(bot, event, self._declaration.command_id):
            return HandlingOutcome(handled=False, fallback_to_matcher=True, fallback_reason="permission_denied")
        result = await self._declaration.execute(
            DirectCommandContext(
                bot=bot,
                event=event,
                bot_id=context.bot_id,
                group_id=context.group_id,
                message_id=context.message_id,
                command_text=context.plain_text.strip(),
            )
        )
        if result.fallback_to_matcher:
            return HandlingOutcome(
                handled=False,
                fallback_to_matcher=True,
                fallback_reason=result.fallback_reason,
            )
        return HandlingOutcome(
            handled=True,
            actions=tuple(SendAction(item.message) for item in result.replies),
            work_jobs=tuple(
                WorkJob.create(kind=item.kind, payload=item.payload, idempotency_key=item.idempotency_key)
                for item in result.work_jobs
            ),
            deferred_actions=tuple(
                DeferredAction(name=item.name, run=item.run, wait_for_completion=item.wait_for_completion)
                for item in result.effects
            ),
            continue_matcher=self._declaration.continue_matcher or result.continue_matcher,
            matcher_exclude_modules=frozenset({self._declaration.module}),
        )


def declaration_routes(declaration: CommandDeclaration) -> tuple[tuple[str, str], ...]:
    if isinstance(declaration, ExactCommandDeclaration):
        return tuple(("exact", command) for command in sorted(declaration.commands))
    return tuple(("prefix", prefix) for prefix in sorted(declaration.prefixes))


def routes_overlap(left: tuple[str, str], right: tuple[str, str]) -> bool:
    left_kind, left_text = left
    right_kind, right_text = right
    if left_kind == right_kind == "exact":
        return left_text == right_text
    if left_kind == right_kind == "prefix":
        return left_text.startswith(right_text) or right_text.startswith(left_text)
    exact = left_text if left_kind == "exact" else right_text
    prefix = left_text if left_kind == "prefix" else right_text
    return exact.startswith(prefix)


def build_declaration_handlers() -> tuple[tuple[DeclaredCommandRuntimeHandler, ...], tuple[DeclarationDiagnostic, ...]]:
    handlers: list[DeclaredCommandRuntimeHandler] = []
    diagnostics: list[DeclarationDiagnostic] = []
    handler_ids: set[str] = set()
    command_owners: dict[str, list[tuple[str, str]]] = {}
    for declaration in command_declarations():
        routes = declaration_routes(declaration)
        commands = tuple(text for _kind, text in routes)
        if declaration.handler_id in handler_ids:
            diagnostics.append(
                DeclarationDiagnostic("duplicate_handler_id", declaration.handler_id, declaration.module, commands)
            )
            continue
        owned_routes = command_owners.get(declaration.module, [])
        if any(routes_overlap(route, owned) for route in routes for owned in owned_routes):
            diagnostics.append(
                DeclarationDiagnostic("overlapping_command", declaration.handler_id, declaration.module, commands)
            )
            continue
        handlers.append(DeclaredCommandRuntimeHandler(declaration))
        handler_ids.add(declaration.handler_id)
        command_owners.setdefault(declaration.module, []).extend(routes)
    return tuple(handlers), tuple(diagnostics)
