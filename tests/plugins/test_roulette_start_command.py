from __future__ import annotations

from packages.roulette import parse_roulette_start_command


def test_parse_roulette_start_command_default():
    assert parse_roulette_start_command("牛牛轮盘") == (True, None)


def test_parse_roulette_start_command_explicit_modes():
    assert parse_roulette_start_command("牛牛轮盘踢人") == (True, 0)
    assert parse_roulette_start_command("牛牛踢人轮盘") == (True, 0)
    assert parse_roulette_start_command("牛牛轮盘禁言") == (True, 1)
    assert parse_roulette_start_command("牛牛禁言轮盘") == (True, 1)


def test_parse_roulette_start_command_non_match():
    assert parse_roulette_start_command("牛牛开枪") == (False, None)
