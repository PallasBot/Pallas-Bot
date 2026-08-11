from __future__ import annotations

import pytest

from pallas.api.runtime import (
    DirectCommandContext,
    DirectCommandResult,
    prefix_command_declarations,
    register_prefix_command_handler,
    remove_exact_command_handlers,
    reply,
    reset_exact_command_handlers,
)


async def execute(context: DirectCommandContext) -> DirectCommandResult:
    return reply(context.command_text)


def setup_function() -> None:
    reset_exact_command_handlers()


def test_register_prefix_command_handler_normalizes_an_immutable_declaration() -> None:
    declaration = register_prefix_command_handler(
        handler_id="sing.generate",
        module="sing",
        prefixes=(" 牛牛唱歌 ", "帕拉斯唱歌"),
        command_id="sing.sing",
        execute=execute,
    )

    assert declaration.handler_id == "sing.generate"
    assert declaration.module == "sing"
    assert declaration.prefixes == frozenset({"牛牛唱歌", "帕拉斯唱歌"})
    assert declaration.command_id == "sing.sing"
    assert "pallas.core" not in type(declaration).__module__
    assert prefix_command_declarations() == (declaration,)


@pytest.mark.parametrize("field", ["handler_id", "module", "command_id"])
def test_prefix_registration_rejects_empty_identifiers(field: str) -> None:
    values = {
        "handler_id": "sing.generate",
        "module": "sing",
        "prefixes": ("牛牛唱歌",),
        "command_id": "sing.sing",
        "execute": execute,
    }
    values[field] = " "

    with pytest.raises(ValueError, match="required"):
        register_prefix_command_handler(**values)


def test_prefix_registration_rejects_empty_prefixes() -> None:
    with pytest.raises(ValueError, match="at least one command prefix is required"):
        register_prefix_command_handler(
            handler_id="sing.generate",
            module="sing",
            prefixes=(),
            command_id="sing.sing",
            execute=execute,
        )


def test_module_removal_and_reset_include_prefix_declarations() -> None:
    register_prefix_command_handler(
        handler_id="sing.generate",
        module="sing",
        prefixes=("牛牛唱歌",),
        command_id="sing.sing",
        execute=execute,
    )

    remove_exact_command_handlers("sing")
    assert prefix_command_declarations() == ()

    register_prefix_command_handler(
        handler_id="sing.generate",
        module="sing",
        prefixes=("牛牛唱歌",),
        command_id="sing.sing",
        execute=execute,
    )
    reset_exact_command_handlers()
    assert prefix_command_declarations() == ()
