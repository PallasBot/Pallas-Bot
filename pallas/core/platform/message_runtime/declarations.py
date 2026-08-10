from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.api.perm import satisfies_command_permission
from pallas.api.runtime import DirectCommandContext, exact_command_declarations
from pallas.core.platform.work_jobs.models import WorkJob

from .models import DeferredAction, HandlingOutcome, MessageContext, SendAction

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

    from pallas.api.runtime import ExactCommandDeclaration


@dataclass(frozen=True, slots=True)
class DeclarationDiagnostic:
    code: str
    handler_id: str
    module: str
    commands: tuple[str, ...]


class ExactCommandRuntimeHandler:
    passive = False
    fallback_on_error = False

    def __init__(self, declaration: ExactCommandDeclaration) -> None:
        self._declaration = declaration
        self.handler_id = declaration.handler_id
        self.modules = frozenset({declaration.module})

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text.strip() in self._declaration.commands

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


def build_declaration_handlers() -> tuple[tuple[ExactCommandRuntimeHandler, ...], tuple[DeclarationDiagnostic, ...]]:
    handlers: list[ExactCommandRuntimeHandler] = []
    diagnostics: list[DeclarationDiagnostic] = []
    handler_ids: set[str] = set()
    command_owners: set[tuple[str, str]] = set()
    for declaration in exact_command_declarations():
        commands = tuple(sorted(declaration.commands))
        if declaration.handler_id in handler_ids:
            diagnostics.append(
                DeclarationDiagnostic("duplicate_handler_id", declaration.handler_id, declaration.module, commands)
            )
            continue
        if any((declaration.module, command) in command_owners for command in declaration.commands):
            diagnostics.append(
                DeclarationDiagnostic("overlapping_command", declaration.handler_id, declaration.module, commands)
            )
            continue
        handlers.append(ExactCommandRuntimeHandler(declaration))
        handler_ids.add(declaration.handler_id)
        command_owners.update((declaration.module, command) for command in declaration.commands)
    return tuple(handlers), tuple(diagnostics)
