from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.request_handler.config import Config
from packages.request_handler.runtime import notify_admins


def _bot(*, self_id: int = 1119799855) -> MagicMock:
    bot = MagicMock()
    bot.self_id = self_id
    bot.send_private_msg = AsyncMock(return_value={"message_id": 42})
    return bot


@pytest.mark.asyncio
async def test_notify_admins_always_notifies_bot_admins_when_switch_off() -> None:
    """号主始终通知；关开关不因「同时是超管」被剔掉。"""
    bot = _bot()
    cfg = Config(request_handler_notify_superusers=False)
    driver = SimpleNamespace(config=SimpleNamespace(superusers={"3023094357"}))

    with (
        patch("packages.request_handler.runtime.get_bot_admins", AsyncMock(return_value=[3023094357, 1306088581])),
        patch("packages.request_handler.runtime.plugin_config", return_value=cfg),
        patch("packages.request_handler.runtime.get_driver", return_value=driver),
        patch("packages.request_handler.runtime.register_approval_notice"),
        patch("packages.request_handler.runtime.persist_approval_notice_map"),
    ):
        ok = await notify_admins(bot, "msg", kind="group", target_id="363439346")

    assert ok is True
    sent = [c.kwargs["user_id"] for c in bot.send_private_msg.await_args_list]
    assert sent == [3023094357, 1306088581]


@pytest.mark.asyncio
async def test_notify_admins_switch_on_also_notifies_pure_superusers() -> None:
    bot = _bot()
    cfg = Config(request_handler_notify_superusers=True)
    driver = SimpleNamespace(config=SimpleNamespace(superusers={"3023094357", "999"}))

    with (
        patch("packages.request_handler.runtime.get_bot_admins", AsyncMock(return_value=[1306088581])),
        patch("packages.request_handler.runtime.plugin_config", return_value=cfg),
        patch("packages.request_handler.runtime.get_driver", return_value=driver),
        patch("packages.request_handler.runtime.register_approval_notice"),
        patch("packages.request_handler.runtime.persist_approval_notice_map"),
    ):
        ok = await notify_admins(bot, "msg", kind="group", target_id="1")

    assert ok is True
    sent = [c.kwargs["user_id"] for c in bot.send_private_msg.await_args_list]
    assert sent == [1306088581, 999, 3023094357]


@pytest.mark.asyncio
async def test_notify_admins_switch_off_skips_pure_superusers() -> None:
    bot = _bot()
    cfg = Config(request_handler_notify_superusers=False)
    driver = SimpleNamespace(config=SimpleNamespace(superusers={"3023094357"}))

    with (
        patch("packages.request_handler.runtime.get_bot_admins", AsyncMock(return_value=[1306088581])),
        patch("packages.request_handler.runtime.plugin_config", return_value=cfg),
        patch("packages.request_handler.runtime.get_driver", return_value=driver),
        patch("packages.request_handler.runtime.register_approval_notice"),
        patch("packages.request_handler.runtime.persist_approval_notice_map"),
    ):
        ok = await notify_admins(bot, "msg", kind="friend", target_id="1")

    assert ok is True
    bot.send_private_msg.assert_awaited_once_with(user_id=1306088581, message="msg")


@pytest.mark.asyncio
async def test_notify_admins_empty_admins_no_superuser_when_switch_off() -> None:
    bot = _bot()
    cfg = Config(request_handler_notify_superusers=False)
    driver = SimpleNamespace(config=SimpleNamespace(superusers={"3023094357"}))

    with (
        patch("packages.request_handler.runtime.get_bot_admins", AsyncMock(return_value=[])),
        patch("packages.request_handler.runtime.plugin_config", return_value=cfg),
        patch("packages.request_handler.runtime.get_driver", return_value=driver),
    ):
        ok = await notify_admins(bot, "msg", kind="group", target_id="1")

    assert ok is False
    bot.send_private_msg.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_admins_empty_admins_falls_back_to_superusers_when_switch_on() -> None:
    bot = _bot()
    cfg = Config(request_handler_notify_superusers=True)
    driver = SimpleNamespace(config=SimpleNamespace(superusers={"3023094357"}))

    with (
        patch("packages.request_handler.runtime.get_bot_admins", AsyncMock(return_value=[])),
        patch("packages.request_handler.runtime.plugin_config", return_value=cfg),
        patch("packages.request_handler.runtime.get_driver", return_value=driver),
        patch("packages.request_handler.runtime.register_approval_notice"),
        patch("packages.request_handler.runtime.persist_approval_notice_map"),
    ):
        ok = await notify_admins(bot, "msg", kind="friend", target_id="1")

    assert ok is True
    bot.send_private_msg.assert_awaited_once_with(user_id=3023094357, message="msg")


@pytest.mark.asyncio
async def test_notify_admins_switch_on_dedupes_superuser_who_is_also_admin() -> None:
    bot = _bot()
    cfg = Config(request_handler_notify_superusers=True)
    driver = SimpleNamespace(config=SimpleNamespace(superusers={"3023094357"}))

    with (
        patch("packages.request_handler.runtime.get_bot_admins", AsyncMock(return_value=[3023094357, 1306088581])),
        patch("packages.request_handler.runtime.plugin_config", return_value=cfg),
        patch("packages.request_handler.runtime.get_driver", return_value=driver),
        patch("packages.request_handler.runtime.register_approval_notice"),
        patch("packages.request_handler.runtime.persist_approval_notice_map"),
    ):
        ok = await notify_admins(bot, "msg", kind="group", target_id="1")

    assert ok is True
    sent = [c.kwargs["user_id"] for c in bot.send_private_msg.await_args_list]
    assert sent == [3023094357, 1306088581]
