from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.message_runtime.models import MessageContext, SendAction


def context(*, plain_text: str) -> MessageContext:
    return MessageContext(
        ingress_id="1:2:3",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=plain_text,
        raw_text=plain_text,
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"help"}),
    )


@pytest.mark.asyncio
async def test_help_native_handler_sends_the_existing_menu_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.help.direct import HelpDirectHandler

    monkeypatch.setattr("packages.help.direct.satisfies_command_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.help.direct.is_command_cooldown_ready", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.help.direct.refresh_command_cooldown", AsyncMock())
    monkeypatch.setattr(
        "packages.help.direct.build_help_menu_rows",
        AsyncMock(return_value=[SimpleNamespace(enabled=True)]),
    )
    monkeypatch.setattr("packages.help.direct.render_plugin_menu_to_image", AsyncMock(return_value=b"image"))
    monkeypatch.setattr("packages.help.direct.get_help_config", lambda: SimpleNamespace(ignored_plugins=[]))

    outcome = await HelpDirectHandler().handle(context(plain_text="牛牛帮助"), bot=MagicMock(), event=MagicMock())

    assert outcome.handled is True
    assert outcome.actions[0].message.type == "image"
    assert outcome.actions[0].message.data["file"] == "base64://aW1hZ2U="


@pytest.mark.asyncio
async def test_help_native_handler_toggles_one_plugin_with_existing_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.help.direct import HelpDirectHandler

    monkeypatch.setattr("packages.help.direct.satisfies_command_permission", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.help.direct.SUPERUSER", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.help.direct.get_help_config", lambda: SimpleNamespace(ignored_plugins=[]))
    monkeypatch.setattr("packages.help.direct.get_help_menu_plugins", lambda **_kwargs: [object()])
    monkeypatch.setattr("packages.help.direct.parse_plugin_toggle_args", lambda *_args, **_kwargs: ["复读"])
    monkeypatch.setattr("packages.help.direct.find_plugin_by_identifier", AsyncMock(return_value=("repeater", None)))
    toggle_plugin = AsyncMock(return_value=(True, "已关闭复读"))
    monkeypatch.setattr("packages.help.direct.toggle_plugin", toggle_plugin)

    event = MagicMock()
    event.user_id = "3023094357"

    outcome = await HelpDirectHandler().handle(context(plain_text="牛牛关闭 复读"), bot=MagicMock(), event=event)

    assert outcome.handled is True
    assert outcome.actions == (SendAction(message="已关闭复读"),)
    toggle_plugin.assert_awaited_once_with(
        "repeater", 2, 1, "disable", is_superuser=True, operator="3023094357"
    )
