from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from src.platform.multi_bot import platform_utils as pu

if TYPE_CHECKING:
    import pytest


def test_resolve_unique_onebot_when_single(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.self_id = "10001"
    monkeypatch.setattr(pu, "list_onebot_v11_bots", lambda: [bot])
    monkeypatch.setattr(pu, "get_bots", lambda: {"10001": bot})
    assert pu.resolve_unique_onebot_v11_bot("test") is bot


def test_resolve_unique_onebot_when_multiple(monkeypatch: pytest.MonkeyPatch) -> None:
    bot1 = MagicMock()
    bot2 = MagicMock()
    monkeypatch.setattr(pu, "list_onebot_v11_bots", lambda: [bot1, bot2])
    monkeypatch.setattr(pu, "get_bots", lambda: {"1": bot1, "2": bot2})
    assert pu.resolve_unique_onebot_v11_bot("test") is None


def test_pick_connected_bot_id_single(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.self_id = "10001"
    monkeypatch.setattr(pu, "get_bots", lambda: {"10001": bot})
    assert pu.pick_connected_bot_id([10001, 10002]) == 10001
