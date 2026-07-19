from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from nonebot.rule import CommandRule

from pallas.core.platform.bot_runtime.duplicate_prefix_check import (
    collect_duplicate_command_prefixes,
    run_duplicate_prefix_check,
)


def _matcher_with_command(*, plugin_name: str, cmd: tuple[str, ...]) -> MagicMock:
    command_rule = CommandRule([cmd])
    checker = SimpleNamespace(call=command_rule)
    rule = SimpleNamespace(checkers=(checker,))
    matcher = MagicMock()
    matcher.plugin_name = plugin_name
    matcher.rule = rule
    return matcher


def test_collect_duplicate_command_prefixes_detects_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    m1 = _matcher_with_command(plugin_name="pallas_plugin_draw.draw", cmd=("牛牛画画",))
    m2 = _matcher_with_command(plugin_name="local.plugins.draw.draw", cmd=("牛牛画画",))
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.duplicate_prefix_check.matchers",
        {5: [m1, m2]},
    )

    conflicts = collect_duplicate_command_prefixes()
    assert len(conflicts) == 1
    assert conflicts[0].command == "牛牛画画"
    assert "pallas_plugin_draw.draw" in conflicts[0].modules
    assert "local.plugins.draw.draw" in conflicts[0].modules


def test_collect_duplicate_command_prefixes_ignores_single_module(monkeypatch: pytest.MonkeyPatch) -> None:
    m1 = _matcher_with_command(plugin_name="pallas_plugin_draw.draw", cmd=("牛牛画画",))
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.duplicate_prefix_check.matchers",
        {5: [m1]},
    )
    assert collect_duplicate_command_prefixes() == []


def test_run_duplicate_prefix_check_strict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    m1 = _matcher_with_command(plugin_name="pallas_plugin_draw.draw", cmd=("牛牛画画",))
    m2 = _matcher_with_command(plugin_name="local.plugins.draw.draw", cmd=("牛牛画画",))
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.duplicate_prefix_check.matchers",
        {5: [m1, m2]},
    )
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.duplicate_prefix_check.duplicate_prefix_strict",
        lambda: True,
    )

    with pytest.raises(RuntimeError, match="重复命令 prefix"):
        run_duplicate_prefix_check()
