from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.platform.ingress import fleet_dispatch_scale as scale

if TYPE_CHECKING:
    import pytest


def test_connected_bot_count_prefers_fleet_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset(range(100, 139)),
    )

    class FakeBots:
        def __init__(self) -> None:
            self._bots = {"100": object()}

        def __len__(self) -> int:
            return len(self._bots)

    monkeypatch.setattr("nonebot.get_bots", lambda: FakeBots())
    assert scale.connected_bot_count() == 39


def test_connected_bot_count_falls_back_to_online_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset(),
    )

    class FakeBots:
        def __len__(self) -> int:
            return 5

    monkeypatch.setattr("nonebot.get_bots", lambda: FakeBots())
    assert scale.connected_bot_count() == 5


def test_scaled_dispatch_int_scales_with_fleet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scale, "connected_bot_count", lambda: 39)
    assert scale.scaled_dispatch_int(16, per_bot=2, cap=64) == 64
    assert scale.scaled_dispatch_int(32, per_bot=1, cap=48) == 39
    assert scale.scaled_dispatch_int(8, per_bot=2, cap=48) == 48
