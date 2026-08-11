from __future__ import annotations

from collections import UserList
from types import SimpleNamespace

import bot_work


async def first_handler(_payload):
    return None


async def second_handler(_payload):
    return None


class EntryPoints(UserList):
    def select(self, *, group: str):
        assert group == "pallas.work_handlers"
        return self


def entry_point(name: str, provider):
    return SimpleNamespace(name=name, value=f"tests:{name}", load=lambda: provider)


def test_external_work_handlers_load_valid_providers_and_keep_first_duplicate() -> None:
    points = EntryPoints([
        entry_point("first", lambda: {"media.generate": first_handler}),
        entry_point("second", lambda: {"media.generate": second_handler, "media.inspect": second_handler}),
    ])

    handlers = bot_work.load_external_work_handlers(entry_points_getter=lambda: points)

    assert handlers == {"media.generate": first_handler, "media.inspect": second_handler}


def test_external_work_handlers_skip_broken_and_malformed_providers() -> None:
    def broken_provider():
        raise RuntimeError("broken")

    points = EntryPoints([
        entry_point("broken", broken_provider),
        entry_point("not-a-map", list),
        entry_point("invalid-handler", lambda: {"media.generate": object()}),
        entry_point("valid", lambda: {"media.inspect": second_handler}),
    ])

    assert bot_work.load_external_work_handlers(entry_points_getter=lambda: points) == {"media.inspect": second_handler}


def test_external_work_handler_provider_is_loaded_atomically() -> None:
    points = EntryPoints([
        entry_point("partial", lambda: {"media.valid": first_handler, "media.invalid": object()}),
    ])

    assert bot_work.load_external_work_handlers(entry_points_getter=lambda: points) == {}


def test_load_work_handlers_keeps_builtins_when_extension_uses_same_kind(monkeypatch) -> None:
    monkeypatch.setattr(bot_work.nonebot, "init", lambda: None)
    monkeypatch.setattr(bot_work, "repeater_work_handlers", lambda: {"repeater.learn": first_handler})
    monkeypatch.setattr(
        bot_work,
        "load_external_work_handlers",
        lambda: {"repeater.learn": second_handler, "media.generate": second_handler},
    )

    assert bot_work.load_work_handlers() == {
        "repeater.learn": first_handler,
        "media.generate": second_handler,
    }
