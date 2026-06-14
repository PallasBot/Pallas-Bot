from __future__ import annotations

from src.plugins.who_is_spy.commands import CMD_END, CMD_OPEN, is_spy_group_command


def test_is_spy_group_command_matches_end() -> None:
    assert is_spy_group_command("牛牛结束") is True


def test_is_spy_group_command_matches_open_with_args() -> None:
    assert is_spy_group_command("牛牛卧底 2") is True


def test_is_spy_group_command_rejects_plain_speech() -> None:
    assert is_spy_group_command("我觉得是卧底") is False


def test_is_spy_group_command_rejects_empty() -> None:
    assert is_spy_group_command("") is False
    assert is_spy_group_command(CMD_END) is True
    assert is_spy_group_command(CMD_OPEN) is True
